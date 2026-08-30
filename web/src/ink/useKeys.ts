/**
 * The only keyboard handler in the application.
 *
 * The rule from `docs/FRONTEND.md` is `1` `2` `3` and `Esc`, nothing else. That rule
 * survives exactly as long as there is one place that implements it: a second listener
 * added "just for this screen" is how a three-key app becomes a twelve-key app without
 * anyone deciding to.
 *
 * Typing is not deciding. A digit typed into the search field on the key rail must reach
 * the field and nothing else, so events originating in a text control are ignored here
 * rather than being fought over with `stopPropagation` at every call site.
 */
import { useEffect, useRef } from "react";

export type InkKey = "1" | "2" | "3" | "Escape";

export type KeyHandlers = Partial<Record<InkKey, () => void>>;

const KEYS: readonly string[] = ["1", "2", "3", "Escape"];

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/**
 * @param handlers what each key does on the screen currently in front of the person
 * @param enabled  false while a screen is busy, so a second press cannot file a second
 *                 decision. The guard belongs here, not in every handler.
 */
export function useKeys(handlers: KeyHandlers, enabled = true): void {
  // Held in a ref so a new object literal on every render does not tear the listener
  // down and put it back — which would drop a keypress landing in the gap.
  const latest = useRef(handlers);
  latest.current = handlers;

  useEffect(() => {
    if (!enabled) return;

    function onKeyDown(event: KeyboardEvent): void {
      if (event.defaultPrevented) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!KEYS.includes(event.key)) return;
      if (isTyping(event.target)) return;

      const run = latest.current[event.key as InkKey];
      if (!run) return;

      event.preventDefault();
      run();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}
