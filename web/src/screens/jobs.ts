/**
 * The four jobs, and how the queue divides into them.
 *
 * Shared by screen 01, which counts them, and screen 04, which works them. One
 * definition, because a home screen promising "13 already paid" and a job screen showing
 * eleven is worse than either screen alone.
 */
import type { Evidence, QueueRow } from "../types";

export type JobId = "paid" | "account" | "incomplete" | "unusual";

export interface Job {
  id: JobId;
  /** What the job is, in the words she would use for it. */
  title: string;
  /** The one question every card in this job asks. */
  question: string;
  /** What `1` and `2` mean here. The two keys change meaning per job; nothing else does. */
  yes: string;
  no: string;
  kinds: Evidence["kind"][];
}

/**
 * Four jobs, not seven.
 *
 * `dashboard/api.py` produces seven kinds of comparison, and the build order asks for
 * four jobs. The mapping is not arbitrary: the first three are distinct questions with
 * distinct answers, and the last four kinds — amount, rate, address, currency — are one
 * question wearing four hats, namely "is this still the supplier you know?". Splitting
 * them would give her four short queues that all end in the same decision.
 */
export const JOBS: Job[] = [
  {
    id: "paid",
    title: "Already paid",
    question: "Is this the same invoice you have already settled?",
    yes: "Not a duplicate",
    no: "Duplicate — do not pay",
    kinds: ["duplicate"],
  },
  {
    id: "account",
    title: "The account changed",
    question: "Did this supplier really change where they get paid?",
    yes: "Confirmed with them",
    no: "Fraud",
    kinds: ["account"],
  },
  {
    id: "incomplete",
    title: "Something is missing",
    question: "Can this be paid without the field they left out?",
    yes: "Pay it anyway",
    no: "Ask them for it",
    kinds: ["missing"],
  },
  {
    id: "unusual",
    title: "Not what they usually send",
    question: "Is this still the supplier you know?",
    yes: "Fine — pay it",
    no: "Not right",
    kinds: ["amount", "rate", "address", "currency", "other"],
  },
];

export function jobOf(row: QueueRow): JobId {
  const kinds = row.evidence.map((e) => e.kind);
  for (const job of JOBS) {
    if (kinds.some((k) => job.kinds.includes(k))) return job.id;
  }
  // A row whose comparison we cannot build still needs a home, and "is this still the
  // supplier you know" is the only one of the four that does not assume a finding.
  return "unusual";
}

/**
 * The queue, divided.
 *
 * Within each job, suppliers with several invoices come first, so the decision that
 * clears the most work is the one she is handed. Without it the batch is real but
 * invisible — it only appears if she happens to land on a repeat. Ties keep the server's
 * order, which is worst-first.
 */
export function groupJobs(rows: QueueRow[]): Map<JobId, QueueRow[]> {
  const by = new Map<JobId, QueueRow[]>(JOBS.map((j) => [j.id, []]));
  for (const row of rows) by.get(jobOf(row))!.push(row);

  for (const [id, list] of by) {
    const count = new Map<string, number>();
    for (const r of list) count.set(r.supplier, (count.get(r.supplier) ?? 0) + 1);
    by.set(id, [...list].sort(
      (a, b) => (count.get(b.supplier) ?? 0) - (count.get(a.supplier) ?? 0),
    ));
  }
  return by;
}

/**
 * How many times she actually has to decide, which is not how many invoices there are.
 *
 * The build order asks for "a time on each job". There is no measurement anywhere in
 * this project of how long Priya takes over an invoice, so a number of minutes here
 * would be invented — and an invented number on the home screen is the kind of thing
 * that gets quoted back later as if it were measured.
 *
 * Decisions are the honest version of the same idea: it is derived, it is what the time
 * would have been a proxy for, and batching means it is genuinely smaller than the pile.
 */
export function decisionsIn(rows: QueueRow[]): number {
  return new Set(rows.map((r) => r.supplier)).size;
}
