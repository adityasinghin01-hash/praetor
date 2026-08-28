/**
 * The queue Priya works.
 *
 * Every sentence about an invoice arrives already translated from
 * `dashboard/language.py`. This file renders them and composes none of its own -- the
 * only English written here is chrome (button labels, headings), and
 * `tests/test_frontend_language.py` scans this source for the same forbidden vocabulary
 * the phrasebook is held to.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, watchQueue } from "./api";
import { Detail } from "./Detail";
import type { QueueResponse, QueueRow, Severity } from "./types";

/** Rule 1: severity is a word and a shape, not only a colour. */
const URGENCY: Record<Severity, { word: string; glyph: string }> = {
  stop: { word: "Do not pay yet", glyph: "!" },
  check: { word: "Needs a look", glyph: "?" },
};

const PER_PAGE = 25;

export function Queue() {
  const [data, setData] = useState<QueueResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [cursor, setCursor] = useState(0);
  const [openRow, setOpenRow] = useState<QueueRow | null>(null);
  // Whether she has actually started moving through the queue. Focus follows the cursor
  // only after that: grabbing the caret on load drags a screen reader past the heading
  // it was about to read, and moves a sighted keyboard user somewhere they did not ask
  // to be. Nothing moves unless she moved it.
  const [navigating, setNavigating] = useState(false);

  const searchRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const load = useCallback(async () => {
    try {
      setData(await api.queue(page, PER_PAGE));
      setError(null);
    } catch (e) {
      // The server's sentence where it gave one; never a status code on screen.
      const said = e instanceof Error ? e.message : "";
      setError(said || "We could not load your queue. Please try again in a moment.");
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    void load();
  }, [load]);

  // Live updates carry a version marker and never content, so the only correct
  // response to one is to re-fetch through the ordinary endpoint.
  useEffect(() => watchQueue(() => void load()), [load]);

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    const needle = filter.trim().toLowerCase();
    if (!needle) return all;
    // Matching on what is already on screen. Nothing is fetched by this, so a search
    // box cannot become a way to ask the server a question somebody else wrote.
    return all.filter((r) =>
      [r.supplier, r.what_is_wrong, r.amount].join(" ").toLowerCase().includes(needle),
    );
  }, [data, filter]);

  useEffect(() => {
    setCursor(0);
  }, [filter, page]);

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const typing =
        document.activeElement instanceof HTMLInputElement ||
        document.activeElement instanceof HTMLTextAreaElement;

      if (event.key === "/" && !typing) {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (typing || openRow) return;

      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setNavigating(true);
        setCursor((c) => Math.min(c + 1, Math.max(rows.length - 1, 0)));
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setNavigating(true);
        setCursor((c) => Math.max(c - 1, 0));
      } else if (event.key === "Enter") {
        const row = rows[cursor];
        if (row) {
          event.preventDefault();
          setOpenRow(row);
        }
      }
    },
    [rows, cursor, openRow],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onKeyDown]);

  // Moving the caret with the cursor is what makes j/k work for a screen reader too:
  // the row is focused, so it is read out. Only once she has started navigating -- see
  // `navigating`.
  useEffect(() => {
    if (navigating && !openRow) rowRefs.current[cursor]?.focus();
  }, [cursor, openRow, navigating]);

  if (loading) {
    return (
      <p className="state" role="status">
        Loading your queue…
      </p>
    );
  }
  if (error) {
    return (
      <div className="state error" role="alert">
        <p>{error}</p>
        <button className="btn" onClick={() => void load()}>
          Try again
        </button>
      </div>
    );
  }
  if (!data) return null;

  const paging = data.page;

  return (
    <>
      <section className="summary" aria-labelledby="headline">
        <h2 className="headline" id="headline">
          {data.headline}
        </h2>
        {data.throughput && <p className="throughput">{data.throughput}</p>}
      </section>

      <div className="controls">
        <label className="sr-only" htmlFor="filter">
          Search this page by supplier or amount
        </label>
        <input
          id="filter"
          className="search"
          ref={searchRef}
          type="search"
          placeholder="Search this page — press / to jump here"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      {/* Announces the count as it changes without stealing the caret. */}
      <p className="sr-only" role="status">
        {rows.length} invoices shown.
      </p>

      {rows.length === 0 ? (
        <p className="state">Nothing here matches what you typed.</p>
      ) : (
        <ul className="queue" aria-label="Invoices waiting for you">
          {rows.map((row, i) => {
            const urgency = URGENCY[row.severity] ?? URGENCY.check;
            return (
              <li key={row.id}>
                <button
                  className={`row ${row.severity}`}
                  ref={(el) => {
                    rowRefs.current[i] = el;
                  }}
                  aria-current={i === cursor ? "true" : undefined}
                  onClick={() => setOpenRow(row)}
                  onFocus={() => setCursor(i)}
                >
                  <span className="mark" aria-hidden="true">
                    {urgency.glyph}
                  </span>
                  {/* Spans, not <p>: a <button> may only contain phrasing content,
                      and block elements inside one are non-conforming HTML that can
                      confuse a screen reader about where the control begins and ends.
                      The CSS gives them the block layout instead. */}
                  <span className="row-main">
                    <span className="urgency">{urgency.word}</span>
                    <span className="supplier">{row.supplier}</span>
                    <span className="wrong">{row.what_is_wrong}</span>
                    <span className="todo">{row.what_to_do}</span>
                  </span>
                  <span className="money">
                    {row.amount}
                    <span className="ccy">{row.currency}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {paging && paging.pages > 1 && (
        <nav className="paging" aria-label="Queue pages">
          <button
            className="btn"
            disabled={!paging.has_previous}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <span className="where">
            Page {paging.page} of {paging.pages} — {paging.total_rows} in total
          </span>
          <button
            className="btn"
            disabled={!paging.has_next}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </nav>
      )}

      <p className="shortcuts">
        <kbd>j</kbd> and <kbd>k</kbd> move down and up · <kbd>Enter</kbd> opens ·{" "}
        <kbd>/</kbd> searches · <kbd>Esc</kbd> closes
      </p>

      {openRow && (
        <Detail
          row={openRow}
          onClose={() => setOpenRow(null)}
          onChanged={() => void load()}
        />
      )}
    </>
  );
}
