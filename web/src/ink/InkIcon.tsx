/**
 * Icons that draw themselves on, even hand.
 *
 * The easing is linear and every stroke starts together — chosen deliberately over a
 * pen-like ease-out. Linear reads as machine-precise, which is what this application is.
 * The value lives in `--draw-ease`; do not restate it here.
 *
 * Paths are drawn with `stroke-dashoffset`, so each one needs a dash length at least as
 * long as itself. `--draw-len` defaults to 120 and can be raised for a longer path.
 */
import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

export interface InkIconProps {
  children: ReactNode;              // raw <path>/<rect>/<line> elements
  /** Dash length; must exceed the longest path in the icon or it will not close up. */
  length?: number;
  size?: string;
  label?: string;                   // omit for decoration, give for meaning
  className?: string;
}

export function InkIcon({ children, length = 120, size, label, className }: InkIconProps) {
  const [drawn, setDrawn] = useState(false);

  // One frame in the undrawn state, then release. Setting both in the same paint gives
  // the browser nothing to transition between and the icon simply appears.
  useEffect(() => {
    const id = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const classes = ["ink-ico", "draw"];
  if (drawn) classes.push("is-drawn");
  if (className) classes.push(className);

  const style = { "--draw-len": String(length), ...(size ? { width: size, height: size } : {}) } as CSSProperties;

  return (
    <svg
      viewBox="0 0 24 24"
      className={classes.join(" ")}
      style={style}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {children}
    </svg>
  );
}
