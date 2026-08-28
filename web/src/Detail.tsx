/**
 * One invoice, opened.
 *
 * A modal dialog is the one place a keyboard user gets stranded most easily, so three
 * things are done deliberately here: the caret moves into the dialog on open, it cannot
 * leave while the dialog is up, and it returns to the row that opened it on close.
 * Without the last one, working a queue by keyboard means starting from the top after
 * every invoice.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Note, QueueRow } from "./types";

interface Props {
  row: QueueRow;
  onClose: () => void;
  onChanged: () => void;
}

export function Detail({ row, onClose, onChanged }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const openedBy = useRef<Element | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [draft, setDraft] = useState("");
  const [saying, setSaying] = useState<string | null>(null);

  useEffect(() => {
    openedBy.current = document.activeElement;
    dialogRef.current?.focus();
    return () => {
      // Back where she was, so the next j or k continues from the same place.
      (openedBy.current as HTMLElement | null)?.focus?.();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void api
      .notes(row.id)
      .then((r) => !cancelled && setNotes(r.notes))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [row.id]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      // The focus trap. A dialog a keyboard user can tab out of, into a page they
      // cannot see, is a dialog they are stuck behind.
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function save(body: string) {
    if (!body.trim()) return;
    try {
      const note = await api.addNote(row.id, body);
      setNotes((n) => [...n, note]);
      setDraft("");
      setSaying("Saved to this invoice.");
      onChanged();
    } catch {
      setSaying("We could not save that. Please try again.");
    }
  }

  return (
    <div
      className="detail-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="detail"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-supplier"
        tabIndex={-1}
      >
        <h2 id="detail-supplier">{row.supplier}</h2>
        <p className="throughput">
          {row.amount} {row.currency}
        </p>

        <dl>
          <dt>What is wrong</dt>
          <dd>{row.what_is_wrong}</dd>
          <dt>What to do</dt>
          <dd>{row.what_to_do}</dd>
          {row.also.length > 0 && (
            <>
              <dt>Also</dt>
              <dd>
                <ul>
                  {row.also.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </dd>
            </>
          )}
          <dt>Invoices seen before</dt>
          <dd>{row.invoices_seen_before}</dd>
        </dl>

        {row.call?.phone && (
          <div className="callout">
            <p>Call them on the number from your own records:</p>
            <p className="phone">{row.call.phone}</p>
            {row.call.name && <p>{row.call.name}</p>}
            <p className="phone-source">
              This number is from {row.call.source ?? "your own records"} — not from the
              invoice.
            </p>
          </div>
        )}

        <label htmlFor="note">What did you find?</label>
        <textarea
          id="note"
          className="search"
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          style={{ width: "100%", marginTop: "0.4rem" }}
        />

        {saying && (
          <p role="status" className="throughput">
            {saying}
          </p>
        )}

        {notes.length > 0 && (
          <ul aria-label="What people have written on this invoice">
            {notes.map((n) => (
              <li key={n.id}>
                {n.body} — {n.author}
              </li>
            ))}
          </ul>
        )}

        <div className="actions">
          <button className="btn primary" onClick={() => void save(draft)}>
            Save what you found
          </button>
          <button className="btn" onClick={() => void save("I called them.")}>
            I called them
          </button>
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
