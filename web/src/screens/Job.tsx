/**
 * Screen 04 — A job.
 *
 * Two of Priya's twelve problems are answered by the *shape* of this screen rather than
 * by anything it says.
 *
 * **Problem 8, "which of the 47 matters".** Forty-seven rows is not a list to work, it is
 * a list to avoid. They group into four jobs, and she picks a job rather than a row —
 * everything inside one job is the same question asked about different invoices, so she
 * only has to think once.
 *
 * **Problem 9, "same supplier, five times".** When a job holds several invoices from one
 * supplier, deciding the first decides them all, because the answer to "has this supplier
 * changed their account" does not change between their invoices. The key label says so
 * before she presses it — a batch action that does not announce its own size is a trap.
 *
 * One card at a time, full screen, no list. `1` saves it and loads the next.
 *
 * Every sentence about an invoice arrives translated from `dashboard/language.py`; the
 * only English here is chrome, and `tests/test_frontend.py` holds this file to that.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, watchQueue } from "../api";
import { Detail } from "../Detail";
import { Arrive, InkButton, KeyRail, useKeys, describeFailure } from "../ink";
import type { Failure } from "../ink";
import { Comparison } from "./Comparison";
import { Draft } from "./Draft";
import { JOBS, groupJobs } from "./jobs";
import type { Job as JobShape, JobId } from "./jobs";
import type { Decision, QueueRow } from "../types";

export function Job({ onDone }: { onDone?: () => void }) {
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [picked, setPicked] = useState<JobId | null>(null);
  const [settled, setSettled] = useState<string[]>([]);
  const [refused, setRefused] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** Synchronous in-flight latch; `busy` is only for rendering. */
  const inFlight = useRef(false);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows((await api.queue(1, 50)).rows);
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

  const grouped = useMemo(() => groupJobs(waiting), [waiting]);

  const job = JOBS.find((j) => j.id === picked) ?? null;
  const inJob = job ? grouped.get(job.id) ?? [] : [];
  const row = inJob[0];

  /** Problem 9: the other invoices from this supplier, in this job, waiting behind it. */
  const siblings = useMemo(
    () => (row ? inJob.filter((r) => r.supplier === row.supplier) : []),
    [inJob, row],
  );

  // The picker's own key. The card below has its own handler; only one of the two is
  // ever mounted, so they cannot both claim `1`.
  const biggestId = useMemo(() => {
    const ranked = [...JOBS]
      .map((j) => ({ id: j.id, n: (grouped.get(j.id) ?? []).length }))
      .sort((a, b) => b.n - a.n)[0];
    return ranked && ranked.n ? ranked.id : null;
  }, [grouped]);

  useKeys({ "1": () => biggestId && setPicked(biggestId) }, !picked);

  const decide = useCallback(async (action: Decision) => {
    // See Verdict: a state flag cannot latch within a single tick, and here each press
    // would fire a request per invoice in the batch.
    if (!row || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    // One answer, applied to every invoice it answers. She confirmed the supplier, not
    // the document, and that fact is true of all of them.
    const ids = siblings.map((r) => r.id);
    setSettled((done) => [...done, ...ids]);
    setRefused(null);
    try {
      const results = await Promise.allSettled(
        ids.map((id) => api.decide(id, action, [])),
      );
      const failed = ids.filter((_, i) => results[i]?.status === "rejected");
      if (failed.length) {
        setSettled((done) => done.filter((d) => !failed.includes(d)));
        const first = results.find((r) => r.status === "rejected");
        const said = first && first.status === "rejected" && first.reason instanceof Error
          ? first.reason.message : "";
        setRefused(said || "Some of those were not recorded. Look at them again.");
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [row, siblings]);

  if (failure) {
    return (
      <section className="job">
        <p className="state" role="alert">{failure.message}</p>
        {/* A retry is offered only where retrying could change the outcome. */}
        {failure.canRetry
          ? <InkButton onClick={() => void load()}>Try again</InkButton>
          : <a className="ink-btn cursor-target" href="/login"><span>Sign in</span></a>}
      </section>
    );
  }

  if (!rows) return <p className="state">Loading…</p>;

  // ---- the four jobs -------------------------------------------------------
  if (!job) {
    const open = waiting.length;
    // Four jobs will not fit on three keys, so the rail offers the one that clears the
    // most work and the rest are reached by Tab — the tiles are real buttons. An empty
    // rail here was the flaw: it told a keyboard user there was no way in.
    const biggest = [...JOBS]
      .map((j) => ({ j, n: (grouped.get(j.id) ?? []).length }))
      .sort((a, b) => b.n - a.n)[0];
    return (
      <section className="job">
        <Arrive>
          <div className="job-pick">
            <p className="job-count display">{open}</p>
            <p className="job-count-note">
              {open === 1 ? "invoice needs you" : "invoices need you"} — four jobs, not{" "}
              {open} separate decisions
            </p>
            <ul className="job-list">
              {JOBS.map((j) => {
                const n = (grouped.get(j.id) ?? []).length;
                return (
                  <li key={j.id}>
                    <button
                      type="button"
                      className="job-tile cursor-target"
                      onClick={() => setPicked(j.id)}
                      disabled={n === 0}
                    >
                      <span className="job-tile-n">{n}</span>
                      <span className="job-tile-title">{j.title}</span>
                      <span className="job-tile-q">{j.question}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </Arrive>
        <KeyRail
          actions={biggest && biggest.n
            ? [{ key: "1", label: `Start on ${biggest.j.title.toLowerCase()} (${biggest.n})`,
                 onPress: () => setPicked(biggest.j.id) }]
            : []}
          escape={{ label: "Done", onPress: () => onDone?.() }}
        />
      </section>
    );
  }

  // ---- one card at a time --------------------------------------------------
  if (!row) {
    return (
      <section className="job">
        <Arrive>
          <p className="verdict-clear display">{job.title} — all clear.</p>
        </Arrive>
        <KeyRail
          actions={[{ key: "3", label: "Back to the jobs", onPress: () => setPicked(null) }]}
          escape={{ label: "Done", onPress: () => onDone?.() }}
        />
      </section>
    );
  }

  const batched = siblings.length > 1;
  const clears = batched ? ` · clears all ${siblings.length}` : "";

  return (
    <JobCard
      job={job}
      row={row}
      left={inJob.length}
      siblings={siblings.length}
      refused={refused}
      clears={clears}
      busy={busy}
      open={open}
      setOpen={setOpen}
      onYes={() => void decide("approved")}
      onNo={() => void decide("rejected")}
      onBack={() => setPicked(null)}
      onDone={onDone}
      reload={load}
    />
  );
}

interface CardProps {
  job: JobShape;
  row: QueueRow;
  left: number;
  siblings: number;
  refused: string | null;
  clears: string;
  busy: boolean;
  open: boolean;
  setOpen: (v: boolean) => void;
  onYes: () => void;
  onNo: () => void;
  onBack: () => void;
  onDone?: () => void;
  reload: () => Promise<void>;
}

function JobCard({
  job, row, left, siblings, refused, clears, busy, open, setOpen,
  onYes, onNo, onBack, onDone, reload,
}: CardProps) {
  useKeys({
    "1": onYes,
    "2": onNo,
    "3": onBack,
    Escape: () => (open ? setOpen(false) : onDone?.()),
  }, !open);

  return (
    <section className="job">
      <Arrive replayKey={row.id}>
        <article className="verdict-card">
          <p className="verdict-urgency">
            {job.title}
            <span className="verdict-left">{left} in this job</span>
          </p>

          <h2 className="verdict-what">{row.what_is_wrong}</h2>
          <p className="verdict-do">{row.what_to_do}</p>

          {/* The card told her to ring them and did not say the number — the one thing
              problem 7 exists to fix, missing from the screen she actually works. */}
          <p className="verdict-who">
            {row.call.phone
              ? `${row.call.name ?? "The supplier"} — ${row.call.phone}`
              : null}
            <span className="verdict-warning">{row.call.warning}</span>
          </p>

          <p className="job-supplier">
            {row.supplier} · {row.amount} {row.currency}
            {siblings > 1 ? (
              <span className="job-batch">
                {siblings} invoices from this supplier are waiting on the same answer.
              </span>
            ) : null}
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

      <KeyRail
        actions={[
          { key: "1", label: `${job.yes}${clears}`, onPress: busy ? undefined : onYes },
          { key: "2", label: `${job.no}${clears}`, onPress: busy ? undefined : onNo },
          { key: "3", label: "Back to the jobs", onPress: onBack },
        ]}
        escape={{ label: "Done", onPress: () => onDone?.() }}
      />

      {open ? <Detail row={row} onClose={() => setOpen(false)} onChanged={() => void reload()} /> : null}
    </section>
  );
}
