/**
 * Whether this person has asked their system for less movement.
 *
 * `styles.css` already flattens every CSS transition and animation for them. It cannot
 * reach the things that do not run on CSS: a WebGL shader, a `requestAnimationFrame`
 * loop, a GSAP timeline. Those have to ask, and this is where they ask.
 *
 * It is a live subscription rather than a one-off read, because the setting can change
 * while the app is open and a screen that only checked at mount would keep moving.
 */
import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia?.(QUERY).matches === true,
  );

  useEffect(() => {
    const mq = window.matchMedia?.(QUERY);
    if (!mq) return;
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
