/**
 * The only place this app talks to the server.
 *
 * It holds no data of its own and caches nothing across a reload. A page with data
 * baked into it has gone stale twice in this project (FINDINGS §5, and again on 27
 * Aug), which is why `dashboard/api.py` exists and why this file is thin: fetch,
 * check the status, hand back typed JSON.
 */
import type { Note, QueueResponse, StoppedResponse } from "./types";

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
  notes: (docId: string) => get<{ notes: Note[] }>("/v1/notes", { doc_id: docId }),

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
