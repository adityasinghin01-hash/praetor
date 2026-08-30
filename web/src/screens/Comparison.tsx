/**
 * What the invoice says, beside what the buyer's own records say.
 *
 * Shared by screens 03 and 04 because it is the same answer in both places: the queue
 * used to state what was wrong and leave Priya to go and look up what it should have
 * been. `dashboard/api.py` builds it; this only lays it out.
 *
 * The left side is a button and the right side is not. That asymmetry is deliberate —
 * the invoice is the thing in question and can be opened to see the value in place; her
 * own records are the reference, and there is nothing to inspect.
 */
import type { Evidence } from "../types";

/** Column headings. Chrome, not a sentence about a finding. */
const SIDES: Record<Evidence["kind"], { left: string; right: string }> = {
  account: { left: "On this invoice", right: "You have paid" },
  duplicate: { left: "This invoice", right: "The one you already have" },
  currency: { left: "On this invoice", right: "Usually" },
  rate: { left: "On this invoice", right: "Usually" },
  address: { left: "On this invoice", right: "Usually" },
  amount: { left: "On this invoice", right: "Usual range" },
  missing: { left: "On this invoice", right: "Usually" },
  other: { left: "On this invoice", right: "In your records" },
};

export function Comparison({ item, onOpen }: { item: Evidence; onOpen: () => void }) {
  const sides = SIDES[item.kind] ?? SIDES.other;
  return (
    <div className="cmp">
      <p className="cmp-field">{item.field}</p>
      <div className="cmp-sides">
        <button type="button" className="cmp-side cursor-target" onClick={onOpen}>
          <span className="cmp-label">{sides.left}</span>
          <span className="cmp-value">{item.on_invoice ?? "Not on the page"}</span>
        </button>
        <div className="cmp-side is-record">
          <span className="cmp-label">{sides.right}</span>
          {item.in_records.length ? (
            item.in_records.map((value) => (
              <span className="cmp-value" key={value}>{value}</span>
            ))
          ) : (
            <span className="cmp-value is-absent">Nothing on file</span>
          )}
        </div>
      </div>
      {item.note ? <p className="cmp-note">{item.note}</p> : null}
    </div>
  );
}
