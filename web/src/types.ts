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

/**
 * The comparison behind one finding: what the invoice says, beside what the buyer's own
 * records say.
 *
 * `note` is written by `dashboard/language.py` like every other sentence here — render
 * it, do not compose one. `in_records` is a list because a supplier can legitimately
 * have more than one known account.
 */
export type EvidenceKind =
  | "account" | "duplicate" | "currency" | "rate" | "address" | "amount" | "missing" | "other";

export interface Evidence {
  /** How to lay it out. Deliberately not the machine's finding code — see dashboard/api.py. */
  kind: EvidenceKind;
  /** Already a person's name for the field, never the parser's. */
  field: string;
  on_invoice: string | null;
  in_records: string[];
  note: string | null;
  /** How many earlier invoices this supplier has, where that is what makes it mean something. */
  seen_before: number | null;
}

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
  /**
   * Who to ring, from the buyer's own records — never from the invoice being checked.
   * `warning` is always present and always rendered: it is what stops someone dialling
   * the number a fraudster printed. See praetor/suppliers.py and dashboard/api.py.
   */
  call: {
    name?: string;
    /** null when there is no number on file, which the warning then explains. */
    phone?: string | null;
    /** From the buyer's own records, like the phone number — never off the invoice. */
    email?: string | null;
    source?: string;
    warning: string;
  };
  invoices_seen_before: number;
  outcome: string;
  outcome_label: string;
  system_said: string;
  decided_by: string | null;
  decided_at: string | null;
  amount_sort: number;
  /** Empty when the system cannot answer the comparison — never a blank side-by-side. */
  evidence: Evidence[];
  /**
   * The email she would otherwise write by hand, composed by `dashboard/language.py`.
   * Null when this finding is not one you write to a supplier about.
   */
  draft: { subject: string; body: string } | null;
  /** Three things she writes again and again, so filing one is a keypress. */
  canned_notes: string[];
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

/**
 * `GET /v1/stopped` — screen 06, for the manager rather than for Priya.
 *
 * `exposure` is deliberately a formatted string kept per currency and never a single
 * total: adding EUR to GBP produces a number that is wrong in a way nobody notices until
 * a finance person reads it, at which point every other figure is in doubt.
 */
export interface StoppedResponse {
  headline: string;
  exposure: string;
  exposure_by_currency: Record<string, number>;
  exposure_note: string;
  payments_stopped: number;
  ai_overruled: number;
  ai_overruled_note: string;
  controls: { what: string; times: number }[];
  decisions: {
    id: string;
    supplier: string;
    decided_by: string | null;
    decided_at: string | null;
    outcome: string;
    outcome_label: string;
    system_said: string;
    evidence_seen: string[];
  }[];
}

export interface Note {
  id: number;
  body: string;
  author: string;
  kind: string;
  at: string;
}

/**
 * What `POST /v1/documents` returns — the outcome of `ingest/pipeline.py`.
 *
 * `action` is the gate's decision. Screen 02 needs it because two of its six states are
 * not knowable from the camera: whether the page is an invoice at all, and what should
 * happen to it, are answers only the pipeline has.
 */
export interface CaptureResult {
  doc_id: string;
  action: string;
  codes: string[];
  spans: unknown;
  error: string | null;
}

/**
 * The two things a person can decide about an invoice they were handed.
 *
 * Mirrors `praetor/store.py:DECISIONS`. Only an approval establishes trust in the vendor
 * master — a rejection deliberately establishes nothing, which is why these are not
 * interchangeable strings anywhere in this app.
 */
export type Decision = "approved" | "rejected";

export interface DecisionRecord {
  tenant_id: string;
  doc_id: string;
  action: Decision;
  approved_by: string;
  codes: string;
  at: string;
}

/**
 * `GET /v1/cleared` — screen 05.
 *
 * `cleared` and `judged` count different things and the screen must not merge them:
 * `cleared` is everything that never reached a person, `judged` is the subset that raised
 * something and was let through anyway. See dashboard/api.py:cleared.
 */
export interface ClearedResponse {
  cleared: number;
  total: number;
  judged: number;
  headline: string;
  judged_note: string;
  spot_check_note: string;
  sample: {
    id: string;
    supplier: string;
    amount: string | null;
    currency: string | null;
    system_said: string;
  }[];
}

/** `GET /v1/gauntlet/documents` — clean invoices a visitor may attack. */
export interface GauntletDoc {
  id: string;
  supplier: string;
  amount: string | null;
  currency: string | null;
}

/** `GET /v1/gauntlet/examples` — starting points drawn from techniques that worked. */
export interface GauntletExample {
  label: string;
  text: string;
}

/**
 * `POST /v1/gauntlet/run` — the real kernel, on a real invoice, with the visitor's line.
 *
 * `steps` is the chain in order with the one that stopped it marked. `would_have_paid`
 * is the server's own sentence about the consequence; the browser never composes it.
 */
export interface GauntletResult {
  doc_id: string;
  injected_text: string;
  steps: { key: string; name: string; passed: boolean; detail: string }[];
  stopped: boolean;
  stopped_at: number | null;
  amount: string | null;
  currency: string | null;
  attacker_account: string | null;
  would_have_paid: string;
  beat: string[];
  is_attack: boolean;
  placement: string;
}
