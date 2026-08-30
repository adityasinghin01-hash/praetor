/**
 * Screen 01 — Today. Home.
 *
 * The old home screen was a queue: forty-seven rows, worst first, and a person left to
 * work out where to start. This one answers three questions in the order she asks them —
 * what happened overnight, what is left, and where do I begin — and then gets out of the
 * way.
 *
 * **On "a time on each job".** The build order asks for one. Nothing in this project
 * measures how long Priya takes over an invoice, so a number of minutes here would be
 * invented, and an invented number on a home screen is the kind that gets quoted back
 * later as though it were measured. `decisionsIn` gives the honest version of the same
 * idea: how many times she actually has to decide, which batching makes genuinely
 * smaller than the pile.
 *
 * Every sentence about the queue arrives from `dashboard/language.py`. The only English
 * written here is chrome.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, watchQueue } from "../api";
import { Arrive, InkButton, InkIcon, KeyRail, useKeys, describeFailure } from "../ink";
import type { Failure } from "../ink";
import { JOBS, decisionsIn, groupJobs } from "./jobs";
import type { JobId } from "./jobs";
import type { QueueResponse } from "../types";

export function Today({
  onScan,
  onJobs,
}: {
  onScan?: () => void;
  onJobs?: (job?: JobId) => void;
}) {
  const [data, setData] = useState<QueueResponse | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.queue(1, 50));
      setFailure(null);
    } catch (e) {
      setFailure(describeFailure(e, "We could not load your queue. Please try again in a moment."));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => watchQueue(() => void load()), [load]);

  const upload = useCallback(async (file: File) => {
    setSending(true);
    setSent(null);
    try {
      const outcome = await api.uploadPdf(file);
      // Name the document rather than saying "done": she can find it again.
      setSent(outcome.doc_id);
      await load();
    } catch (e) {
      setFailure(describeFailure(e, "That file was not accepted. Try a PDF of the invoice."));
    } finally {
      setSending(false);
    }
  }, [load]);

  useKeys({
    "1": () => onScan?.(),
    "2": () => fileRef.current?.click(),
    "3": () => onJobs?.(),
  });

  if (!data && !failure) return <p className="state">Loading…</p>;

  const grouped = data ? groupJobs(data.rows) : null;

  return (
    <section className="today">
      <Arrive>
        <div className="today-head">
          {/* The win first. She is measured on volume, and the system is making her
              look good; the count of what is left comes after that, not before. */}
          <p className="today-headline display">{data?.headline}</p>
          {data?.throughput ? <p className="today-through">{data.throughput}</p> : null}
        </div>

        <div className="today-entries">
          <button type="button" className="entry cursor-target" onClick={() => onScan?.()}>
            <InkIcon length={90} size="2rem">
              <rect x="3" y="6" width="18" height="13" />
              <circle cx="12" cy="12.5" r="3.5" />
            </InkIcon>
            <span className="entry-title">Scan a page</span>
            <span className="entry-note">The camera reads it. No shutter button.</span>
            <span className="entry-key" aria-hidden="true">1</span>
          </button>

          <button
            type="button"
            className="entry cursor-target"
            onClick={() => fileRef.current?.click()}
            disabled={sending}
          >
            <InkIcon length={90} size="2rem">
              <path d="M12 17V5" />
              <path d="M7 10l5-5 5 5" />
              <path d="M4 19h16" />
            </InkIcon>
            <span className="entry-title">{sending ? "Sending…" : "Upload a PDF"}</span>
            <span className="entry-note">
              {sent ? `Read — ${sent}` : "One you already have on file."}
            </span>
            <span className="entry-key" aria-hidden="true">2</span>
          </button>

          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            aria-label="Upload an invoice PDF"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";           // so the same file can be sent twice
              if (file) void upload(file);
            }}
          />
        </div>

        {failure ? (
          <p className="today-error" role="alert">
            {failure.message}{" "}
            {failure.canRetry
              ? <InkButton onClick={() => void load()}>Try again</InkButton>
              : <a className="ink-btn cursor-target" href="/login"><span>Sign in</span></a>}
          </p>
        ) : null}

        {grouped ? (
          <div className="today-jobs">
            <p className="today-jobs-head">
              What is left, in {JOBS.filter((j) => (grouped.get(j.id) ?? []).length).length} jobs
            </p>
            <ul className="job-list">
              {JOBS.map((j) => {
                const rows = grouped.get(j.id) ?? [];
                if (!rows.length) return null;
                const decisions = decisionsIn(rows);
                return (
                  <li key={j.id}>
                    <button
                      type="button"
                      className="job-tile cursor-target"
                      onClick={() => onJobs?.(j.id)}
                    >
                      <span className="job-tile-n">{rows.length}</span>
                      <span className="job-tile-title">{j.title}</span>
                      <span className="job-tile-q">
                        {decisions === rows.length
                          ? `${decisions} ${decisions === 1 ? "decision" : "decisions"}`
                          : `${decisions} ${decisions === 1 ? "decision" : "decisions"}, because some are the same supplier`}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </Arrive>

      <KeyRail
        actions={[
          { key: "1", label: "Scan", onPress: () => onScan?.() },
          { key: "2", label: "Upload", onPress: () => fileRef.current?.click() },
          { key: "3", label: "Start on a job", onPress: () => onJobs?.() },
        ]}
      />
    </section>
  );
}
