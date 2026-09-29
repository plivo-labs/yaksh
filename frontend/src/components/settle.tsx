import { type ReactNode, useState } from "react";

/** Replays a short entrance each time `value` changes after the first render, so a change that
 * arrives by itself, such as a call ending, is noticed. The first render stays still, so loading
 * a page does not animate. */
export function Settle({ value, children }: { value: string; children: ReactNode }) {
  const [first] = useState(value);
  if (value === first) return children;
  return (
    <span
      key={value}
      className="inline-flex transition-[opacity,scale] duration-200 ease-out starting:scale-95 starting:opacity-0 motion-reduce:starting:scale-100"
    >
      {children}
    </span>
  );
}
