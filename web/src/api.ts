/**
 * The only place this app talks to the server.
 *
 * It holds no data of its own and caches nothing across a reload. A page with data
 * baked into it has gone stale twice in this project (FINDINGS §5, and again on 27
 * Aug), which is why `dashboard/api.py` exists and why this file is thin: fetch,
 * check the status, hand back typed JSON.
 */
import type {
  CaptureResult,
  ClearedResponse,
  GauntletDoc,
  GauntletExample,
  GauntletResult,
  Decision,
  DecisionRecord,
  Note,
  QueueResponse,
  StoppedResponse,
} from "./types";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
  const query = new URLSearchParams(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  ).toString();
  const response = await fetch(query ? `${path}?${query}` : path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await describe(response));
  }
  return (await response.json()) as T;
}

async function describe(response: Response): Promise<string> {
  // The server's own words where it has them. Never a status code on screen: a number
  // is not something anyone should have to look up to know what happened.
  try {
    const body = (await response.json()) as { error?: string; detail?: string };
    return body.error ?? body.detail ?? "";
  } catch {
    return "";
  }
}

export const api = {
  queue: (page: number, perPage: number) =>
    get<QueueResponse>("/v1/queue", { page, per_page: perPage }),
  stopped: () => get<StoppedResponse>("/v1/stopped"),
  cleared: () => get<ClearedResponse>("/v1/cleared"),

  // Screen 07 is deliberately open: requiring a login to attack a demo defeats its
  // point, and it touches only the synthetic corpus.
  gauntletDocs: () => get<{ documents: GauntletDoc[] }>("/v1/gauntlet/documents"),
  gauntletExamples: () => get<{ examples: GauntletExample[] }>("/v1/gauntlet/examples"),

  async gauntletRun(docId: string, text: string): Promise<GauntletResult> {
    const response = await fetch("/v1/gauntlet/run", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId, text }),
    });
    if (!response.ok) throw new ApiError(response.status, await describe(response));
    return (await response.json()) as GauntletResult;
  },
  notes: (docId: string) => get<{ notes: Note[] }>("/v1/notes", { doc_id: docId }),

  /**
   * Send a captured page.
   *
   * The server accepts PDFs only and checks the bytes as well as the name, so the frame
   * is wrapped by `lib/pageToPdf.ts` before it gets here. It runs the same
   * `ingest/pipeline.py` an Eventarc-delivered document runs — there is no second intake
   * path, and this call deliberately does not create one.
   */
  async sendPage(pdf: Uint8Array, filename: string): Promise<CaptureResult> {
    const form = new FormData();
    form.append("file", new Blob([pdf as BlobPart], { type: "application/pdf" }), filename);
    const response = await fetch("/v1/documents", {
      method: "POST",
      credentials: "same-origin",
      body: form,
    });
    if (!response.ok) throw new ApiError(response.status, await describe(response));
    return (await response.json()) as CaptureResult;
  },

  /**
   * Record what Priya decided. This is what makes a screen end in an action.
   *
   * Deliberately not retried on failure. The server refuses a second decision with 409
   * precisely because a double approval is a double payment, so a retry that "helpfully"
   * succeeds would be defeating the guard rather than recovering from a blip.
   */
  async decide(docId: string, action: Decision, codes: string[] = []): Promise<DecisionRecord> {
    const response = await fetch("/v1/decisions", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId, action, codes }),
    });
    if (!response.ok) throw new ApiError(response.status, await describe(response));
    return (await response.json()) as DecisionRecord;
  },

  /**
   * Send a PDF she already has — the other half of Scan.
   *
   * Same endpoint, same pipeline. The server checks the extension *and* the magic bytes,
   * so an unhelpful file is refused there rather than second-guessed here; whatever it
   * says comes back as the error, in its own words.
   */
  async uploadPdf(file: File): Promise<CaptureResult> {
    const form = new FormData();
    form.append("file", file, file.name);
    const response = await fetch("/v1/documents", {
      method: "POST",
      credentials: "same-origin",
      body: form,
    });
    if (!response.ok) throw new ApiError(response.status, await describe(response));
    return (await response.json()) as CaptureResult;
  },

  async addNote(docId: string, body: string): Promise<Note> {
    const response = await fetch("/v1/notes", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId, body }),
    });
    if (!response.ok) throw new ApiError(response.status, await describe(response));
    return (await response.json()) as Note;
  },
};

/**
 * Subscribe to queue changes.
 *
 * The stream carries a version marker and never queue content, so this deliberately
 * ignores the payload and simply re-fetches. A dropped or partially delivered stream
 * therefore cannot put wrong data on a screen -- the worst case is a refresh that does
 * not happen, and the view is still whole.
 */
export function watchQueue(onChange: () => void): () => void {
  if (typeof EventSource === "undefined") return () => {};
  const source = new EventSource("/v1/events", { withCredentials: true });
  source.addEventListener("queue", () => onChange());
  return () => source.close();
}
