import type { ReactNode } from "react";

/** The step's buttons, kept in view at the bottom of the page. The shell's scroll area keeps a
 * bottom padding that a sticky element stops above, so the shadow fills it and nothing scrolls
 * into view below the buttons. */
export function StepFooter({ children }: { children: ReactNode }) {
  return (
    <div className="sticky bottom-0 z-10 mt-auto flex flex-wrap items-center gap-x-3 gap-y-2 border-t bg-background py-4 shadow-[0_1.25rem_0_0_var(--color-background)]">
      {children}
    </div>
  );
}
