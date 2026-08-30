/**
 * The locked design, as components.
 *
 * Screens import from here and never restate a value. The twelve decisions behind these
 * are in `docs/FRONTEND.md`; the tokens they read are at the foot of `styles.css`.
 */
export { InkButton } from "./InkButton";
export type { InkButtonProps } from "./InkButton";

export { InkIcon } from "./InkIcon";
export type { InkIconProps } from "./InkIcon";

export { Arrive } from "./Arrive";
export type { ArriveProps } from "./Arrive";

export { KeyRail } from "./KeyRail";
export type { KeyRailProps, RailAction } from "./KeyRail";

export { useKeys } from "./useKeys";
export { useReducedMotion } from "./useReducedMotion";
export { describeFailure } from "./failure";
export type { Failure } from "./failure";
export type { InkKey, KeyHandlers } from "./useKeys";
