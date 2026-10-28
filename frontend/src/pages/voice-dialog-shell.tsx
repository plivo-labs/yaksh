import type { ReactNode } from "react";

import { DiscardConfirm } from "@/components/confirm-dialogs";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { CloseGuard } from "@/hooks/use-close-guard";
import type { VoicePreview } from "@/hooks/use-voice-preview";
import type { Language, VoiceSettings } from "@/lib/types";

/** The previews of one voice dialog. `play` keeps each key it plays, so that `stop` stops all of
 * them when the dialog closes or the voice to preview changes. */
export interface DialogPreview extends Pick<VoicePreview, "isPlaying" | "isLoading" | "error"> {
  play: (key: string, voice: VoiceSettings, language: Language) => void;
  stop: () => void;
}

/** The part of a voice dialog that scrolls, between its top and its footer. */
export function VoiceDialogBody({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 py-1">
      <div className="pb-6">{children}</div>
    </div>
  );
}

/** The frame of a voice dialog. It asks before it throws away unsaved changes, stays open while
 * `locked`, and calls `onClosed` once it has closed. */
export function VoiceDialogShell({
  title,
  guard,
  locked = false,
  onClosed,
  children,
}: {
  title: string;
  guard: CloseGuard;
  locked?: boolean;
  onClosed: () => void;
  children: ReactNode;
}) {
  return (
    <Dialog
      open={guard.open}
      onOpenChange={(next) => !next && !locked && guard.requestClose()}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-xl">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        {children}
        <DiscardConfirm subject="voice" {...guard.discard} />
      </DialogContent>
    </Dialog>
  );
}
