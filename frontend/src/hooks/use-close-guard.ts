import { useState } from "react";

/** Open state for an editing dialog that asks before it throws away unsaved changes. */
export function useCloseGuard(dirty: boolean) {
  const [open, setOpen] = useState(true);
  const [confirming, setConfirming] = useState(false);
  return {
    open,
    close: () => setOpen(false),
    requestClose: () => (dirty ? setConfirming(true) : setOpen(false)),
    discard: {
      open: confirming,
      onOpenChange: setConfirming,
      onDiscard: () => {
        setConfirming(false);
        setOpen(false);
      },
    },
  };
}
