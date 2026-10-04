/** A short fade for content that appears after the first render: an error, or a field that a
 * choice reveals. */
export const APPEAR = "transition-opacity duration-150 ease-out starting:opacity-0";

/** Content that arrives while the user watches, such as a live transcript turn. */
export const RISE =
  "transition-[opacity,translate] duration-200 ease-out starting:translate-y-1 starting:opacity-0 motion-reduce:starting:translate-y-0";

/** Content that opens below the control that revealed it. */
export const REVEAL =
  "transition-[opacity,translate] duration-200 ease-out starting:-translate-y-1 starting:opacity-0 motion-reduce:starting:translate-y-0";
