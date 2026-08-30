/**
 * The toolbar, which is the three keys — and the search that sits on it.
 *
 * There is no menu and no dock. The rail exists to teach the only controls that exist,
 * so it shows the keys that do something on *this* screen and dims the ones that do not,
 * rather than presenting a fixed row that lies about what is available.
 *
 * Search is a ruled line rather than a box: one weight of ink and a seal-red caret.
 */
import type { InkKey } from "./useKeys";

export interface RailAction {
  key: Exclude<InkKey, "Escape">;
  label: string;
  onPress?: () => void;
}

export interface KeyRailProps {
  actions: RailAction[];
  /** Omitted on screens where there is nothing to search — screen 02, for instance. */
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
  };
  /** What `Esc` does here, named. A key whose effect is unstated is a key nobody presses. */
  escape?: { label: string; onPress: () => void };
}

export function KeyRail({ actions, search, escape }: KeyRailProps) {
  return (
    <div className="ink-rail">
      <div className="keys">
        {actions.map((action) => (
          <button
            key={action.key}
            type="button"
            className="cursor-target"
            onClick={action.onPress}
            disabled={!action.onPress}
          >
            <b aria-hidden="true">{action.key}</b>
            <span>{action.label}</span>
          </button>
        ))}
        {escape ? (
          <button type="button" className="cursor-target" onClick={escape.onPress}>
            <b aria-hidden="true">Esc</b>
            <span>{escape.label}</span>
          </button>
        ) : null}
      </div>

      {search ? (
        <label className="ink-search cursor-target">
          <svg viewBox="0 0 24 24" className="ink-ico" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <line x1="16" y1="16" x2="21" y2="21" />
          </svg>
          <span className="sr-only">Search invoices</span>
          <input
            type="search"
            value={search.value}
            placeholder={search.placeholder ?? "invoice, supplier, amount"}
            onChange={(event) => search.onChange(event.target.value)}
          />
          <i className="ink-caret" aria-hidden="true" />
        </label>
      ) : null}
    </div>
  );
}
