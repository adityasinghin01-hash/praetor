/**
 * The ruled block, with the stamp press.
 *
 * Two of the twelve decisions live here and nowhere else: three line weights rather than
 * one uniform box, and a press that depresses onto its own shadow. Both are in
 * `styles.css` as `.ink-btn`; this file exists so a screen writes what the button *is*
 * rather than restating how it looks.
 *
 * `cursor-target` is what `TargetCursor` looks for — it is the class that makes the four
 * corners lock on, so every button carries it.
 */
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { InkKey } from "./useKeys";

export interface InkButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** The key that does the same thing. Shown as a cap, so the keyboard is discoverable. */
  shortcut?: Exclude<InkKey, "Escape">;
  /** Solid ink rather than paper. Grain never applies here — see `.ink-btn.is-ink`. */
  tone?: "paper" | "ink";
  children: ReactNode;
}

export function InkButton({
  shortcut,
  tone = "paper",
  children,
  className,
  type = "button",
  ...rest
}: InkButtonProps) {
  const classes = ["ink-btn", "cursor-target"];
  if (tone === "ink") classes.push("is-ink");
  if (className) classes.push(className);

  return (
    <button type={type} className={classes.join(" ")} {...rest}>
      {shortcut ? <kbd aria-hidden="true">{shortcut}</kbd> : null}
      <span>{children}</span>
    </button>
  );
}
