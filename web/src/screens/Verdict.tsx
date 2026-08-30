/**
 * Screen 03 — Verdict.
 *
 * One invoice, one thing to do, three keys. The rule from `docs/FRONTEND.md` is that
 * every screen ends in an action, and this is the screen that rule was written for: the
 * queue used to describe what was wrong and leave Priya to go and find the answer.
 *
 * Every sentence about an invoice arrives already translated from
 * `dashboard/language.py`. Nothing here composes one — the only English written in this
 * file is chrome, and `tests/test_frontend.py` scans it for the vocabulary the phrasebook
 * forbids.
 *
 * **The decision is optimistic, the guard is not.** The card advances the instant she
 * presses a key, because waiting on a round trip forty-seven times a night is the tax the
 * old screen charged. If the server refuses — somebody already decided this, or it was
 * never escalated — the card comes back with what the server said. `api.decide` does not
 * retry, and neither does this: a double approval is a double payment.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, watchQueue } from "../api";
import { Detail } from "../Detail";
import { Arrive, InkButton, KeyRail, useKeys, describeFailure } from "../ink";
import type { Failure } from "../ink";
import { Comparison } from "./Comparison";
import { Draft } from "./Draft";
import type { Decision, QueueRow, Severity } from "../types";

/** Rule 1: severity is a word and a shape, never a colour on its own. */
const URGENCY: Record<Severity, { word: string; glyph: string }> = {
  stop: { word: "Do not pay yet", glyph: "!" },
  check: { word: "Needs a look", glyph: "?" },
};

export function Verdict({ onScan, onDone }: { onScan?: () => void; onDone?: () => void }) {
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [at, setAt] = useState(0);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** Synchronous in-flight latch; `busy` is only for rendering. */
  const inFlight = useRef(false);
  const [open, setOpen] = useState(false);
  /** Documents decided in this sitting, so a re-fetch cannot hand them back. */
  const [settled, setSettled] = useState<string[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await api.queue(1, 25);
      setRows(data.rows);
      setFailure(null);
    } catch (e) {
      setFailure(describeFailure(e, "We could not load your queue. Please try again in a moment."));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => watchQueue(() => void load()), [load]);

  const waiting = useMemo(
    () => (rows ?? []).filter((r) => !settled.includes(r.id)),
    [rows, settled],
  );
  const row = waiting[Math.min(at, Math.max(waiting.length - 1, 0))];

  const advance = useCallback(() => {
    setRefused(null);
    setAt((n) => n + 1);
  }, []);

  const decide = useCallback(async (action: Decision) => {
    // The guard has to be a ref, not state. `setBusy(true)` does not take effect until
    // the next render, so six keypresses in one tick all read `busy === false` and six
    // requests go out for the same invoice. The server refuses five of them, which is
    // the guard working — but the screen then tells her the decision she just made was
    // "already approved", and puts the invoice back. A ref updates synchronously.
    if (!row || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    const id = row.id;
    // Optimistic: she is already looking at the next invoice.
    setSettled((done) => [...done, id]);
    setRefused(null);
    try {
      await api.decide(id, action, []);
    } catch (e) {
      // Put it back and say what the server said. A refusal here is the guard working.
      setSettled((done) => done.filter((d) => d !== id));
      const said = e instanceof Error ? e.message : "";
      setRefused(said || "That decision was not recorded. Look at this one again.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [row]);

  useKeys({
    "1": () => void decide("approved"),
    "2": () => void decide("rejected"),
    "3": () => (onScan ? onScan() : advance()),
    Escape: () => (open ? setOpen(false) : onDone?.()),
  }, !open);

  if (failure) {
    return (
      <section className="verdict">
        <p className="state" role="alert">{failure.message}</p>
        {/* A retry is offered only where retrying could change the outcome. */}
        {failure.canRetry
          ? <InkButton onClick={() => void load()}>Try again</InkButton>
          : <a className="ink-btn cursor-target" href="/login"><span>Sign in</span></a>}
      </section>
    );
  }

  if (!rows) return <p className="state">Loading…</p>;

  if (!row) {
    return (
      <section className="verdict">
        <Arrive>
          <p className="verdict-clear display">Nothing is waiting for you.</p>
        </Arrive>
        <KeyRail
          actions={[{ key: "3", label: "Scan a page", onPress: onScan }]}
          escape={{ label: "Done", onPress: () => onDone?.() }}
        />
      </section>
    );
  }

  const urgency = URGENCY[row.severity];

  return (
    <section className="verdict">
      <Arrive replayKey={row.id}>
        <article className="verdict-card">
          <p className="verdict-urgency">
            <span className="glyph" aria-hidden="true">{urgency.glyph}</span>
            {urgency.word}
            <span className="verdict-left">{waiting.length} left</span>
          </p>

          <h2 className="verdict-what">{row.what_is_wrong}</h2>
          <p className="verdict-do">{row.what_to_do}</p>

          <p className="verdict-who">
            {row.call.phone ? `${row.call.name ?? "The supplier"} — ${row.call.phone}` : null}
            <span className="verdict-warning">{row.call.warning}</span>
          </p>

          {row.evidence.length ? (
            <div className="cmp-set">
              {row.evidence.map((item, i) => (
                <Comparison key={`${item.kind}-${i}`} item={item} onOpen={() => setOpen(true)} />
              ))}
            </div>
          ) : null}

          {/* Secondary findings. They were on the row all along and shown nowhere,
              so a card with three things wrong looked like a card with one. */}
          {row.also.length ? (
            <ul className="also">
              {row.also.map((line) => <li key={line}>{line}</li>)}
            </ul>
          ) : null}

          <Draft row={row} />

          {refused ? <p className="verdict-refused" role="alert">{refused}</p> : null}
        </article>
      </Arrive>

      {/* While a decision is in flight the keys go inactive. The ref latch already
          stops a second request; this is so she can see why the third press did
          nothing. */}
      <KeyRail
        actions={[
          { key: "1", label: "Confirmed", onPress: busy ? undefined : () => void decide("approved") },
          { key: "2", label: "Fraud", onPress: busy ? undefined : () => void decide("rejected") },
          { key: "3", label: onScan ? "Scan the next page" : "Skip", onPress: () => (onScan ? onScan() : advance()) },
        ]}
        escape={{ label: "Done", onPress: () => onDone?.() }}
      />

      {open ? <Detail row={row} onClose={() => setOpen(false)} onChanged={() => void load()} /> : null}
    </section>
  );
}
