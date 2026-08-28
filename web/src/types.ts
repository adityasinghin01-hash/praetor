/**
 * The shape of what `dashboard/api.py` returns.
 *
 * Every user-facing sentence in these types -- `what_is_wrong`, `what_to_do`,
 * `headline`, `outcome_label` -- is written by `dashboard/language.py` and arrives
 * already translated. **The frontend never composes a sentence about a finding.**
 * There is one place to audit the words a person reads, and it is not here.
 */

/** How much attention a row needs. Never the only signal: see `SEVERITY_LABEL`. */
export type Severity = "stop" | "check";

export interface QueueRow {
  id: string;
  supplier: string;
  amount: string;
  currency: string;
  /** Already-translated sentence. Render it; do not parse it. */
  what_is_wrong: string;
  /** Already-translated instruction. */
  what_to_do: string;
  severity: Severity;
  also: string[];
  call: { name?: string; phone?: string; source?: string } | null;
  invoices_seen_before: number;
  outcome: string;
  outcome_label: string;
  system_said: string;
  decided_by: string | null;
  decided_at: string | null;
  amount_sort: number;
}

export interface PageInfo {
  page: number;
  per_page: number;
  pages: number;
  total_rows: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface QueueResponse {
  headline: string;
  waiting: number;
  handled: number;
  total: number;
  throughput: string;
  rows: QueueRow[];
  /** Present on the FastAPI transport only. */
  page?: PageInfo;
}

export interface StoppedResponse {
  headline: string;
  [key: string]: unknown;
}

export interface Note {
  id: number;
  body: string;
  author: string;
  kind: string;
  at: string;
}
