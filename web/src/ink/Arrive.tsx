/**
 * Lift and settle.
 *
 * Plays when the panel is actually on screen, not when the component mounts. That
 * distinction cost a round of review: an arrival fired at mount, on a page where the
 * panel sat below the fold, had always finished by the time anyone scrolled to it — so
 * the animation was correct and invisible, which is indistinguishable from broken.
 *
 * It re-arms on the way out, so scrolling back plays it again.
 */
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

export interface ArriveProps {
  children: ReactNode;
  className?: string;
  /** Change this and the panel re-arrives — pass the id of whatever is being shown. */
  replayKey?: string | number;
}

export function Arrive({ children, className, replayKey }: ArriveProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  // A new card is a new arrival: drop back to the pre-arrival state, then let the
  // observer below bring it in. Without this the second invoice would simply appear.
  useEffect(() => {
    setShown(false);
  }, [replayKey]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (typeof IntersectionObserver === "undefined") {
      setShown(true);            // jsdom, and anything else without the observer
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => setShown(Boolean(entries[0]?.isIntersecting)),
      { threshold: 0.35 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [replayKey]);

  const classes = ["ink-arrive"];
  if (shown) classes.push("is-in");
  if (className) classes.push(className);

  return (
    <div ref={ref} className={classes.join(" ")}>
      {children}
    </div>
  );
}
