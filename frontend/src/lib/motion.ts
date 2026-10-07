/** A short fade for content that appears after the first render: an error, or a field that a
 * choice reveals. */
export const APPEAR = "transition-opacity duration-150 ease-out starting:opacity-0";

/** Content that arrives while the user watches, such as a live transcript turn. */
export const RISE =
  "transition-[opacity,translate] duration-200 ease-out starting:translate-y-1 starting:opacity-0 motion-reduce:starting:translate-y-0";

/** Content that opens below the control that revealed it. */
export const REVEAL =
  "transition-[opacity,translate] duration-200 ease-out starting:-translate-y-1 starting:opacity-0 motion-reduce:starting:translate-y-0";

/** A wizard step that follows the current one: it slides in from the right. */
export const STEP_FORWARD =
  "transition-[opacity,translate] duration-200 ease-out starting:translate-x-2 starting:opacity-0 motion-reduce:starting:translate-x-0";

/** A wizard step before the current one: it slides in from the left. */
export const STEP_BACK =
  "transition-[opacity,translate] duration-200 ease-out starting:-translate-x-2 starting:opacity-0 motion-reduce:starting:translate-x-0";
