/**
 * The email, already written.
 *
 * Priya's problem 6 asks for the missing field to be *named and the email drafted*;
 * problem 11 accepts that the phone call cannot be automated and asks for writing
 * instead. They are the same feature.
 *
 * The text is shown rather than hidden behind a button. She is the one whose name goes
 * on it, so she reads it before it goes — and if her machine has no mail client set up,
 * a visible draft can still be copied, where a `mailto:` that silently does nothing
 * cannot.
 */
import type { QueueRow } from "../types";

export function Draft({ row }: { row: QueueRow }) {
  if (!row.draft) return null;
  const to = row.call.email ?? "";
  const href =
    `mailto:${encodeURIComponent(to)}` +
    `?subject=${encodeURIComponent(row.draft.subject)}` +
    `&body=${encodeURIComponent(row.draft.body)}`;

  return (
    <div className="draft">
      <p className="stopped-label">The email, already written</p>
      <p className="draft-to">
        {to || "No address on file — send it from your own systems."}
      </p>
      <p className="draft-subject">{row.draft.subject}</p>
      <p className="draft-body">{row.draft.body}</p>
      {to ? (
        <a className="ink-btn cursor-target draft-send" href={href}>
          <span>Open it in your mail</span>
        </a>
      ) : null}
    </div>
  );
}
