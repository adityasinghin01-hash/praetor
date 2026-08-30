/**
 * What to say when a request fails, and whether trying again could possibly help.
 *
 * Two rules this project already holds itself to: never a status code on screen, and the
 * server's own words where it has them. A third was missing, and it is the one that
 * matters most on a screen someone is stuck on — **an action that cannot work must not be
 * offered.** A session that has ended showed "not signed in" beside a Try again button
 * that would fail identically every time it was pressed.
 */
import { ApiError } from "../api";

export interface Failure {
  /** A sentence, never a code. */
  message: string;
  /** False when pressing the same button again cannot change the outcome. */
  canRetry: boolean;
}

export function describeFailure(error: unknown, fallback: string): Failure {
  if (error instanceof ApiError) {
    // 401/403: the request was fine and the session was not. Retrying is the one thing
    // that certainly will not fix it.
    if (error.status === 401 || error.status === 403) {
      return {
        message: "Your session has ended. Sign in again to carry on.",
        canRetry: false,
      };
    }
    if (error.message) return { message: error.message, canRetry: true };
  }
  const said = error instanceof Error ? error.message : "";
  return { message: said || fallback, canRetry: true };
}
