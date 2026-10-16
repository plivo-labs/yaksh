import { type ReactNode, useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useEndConversation } from "@/lib/queries";
import type { ConversationStatus } from "@/lib/types";

/** Asks before an action. `onConfirm` gets `close`, to call when the request ends; a failure
 * shows `error` in the dialog so the reason is not lost. */
export function ConfirmDialog({
  title,
  description,
  note,
  action,
  cancel = "Cancel",
  destructive = false,
  pending,
  error,
  open,
  onOpenChange,
  onConfirm,
}: {
  title: ReactNode;
  description: ReactNode;
  note?: ReactNode;
  action: string;
  cancel?: string;
  destructive?: boolean;
  pending: boolean;
  error?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (close: () => void) => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {note && <p className="text-s-400 text-muted-foreground">{note}</p>}
        {error && <p className="text-p-400 text-destructive">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel>{cancel}</AlertDialogCancel>
          <AlertDialogAction
            variant={destructive ? "destructive" : "default"}
            disabled={pending}
            onClick={() => onConfirm(() => onOpenChange(false))}
          >
            {pending && <Spinner />}
            {action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** Asks before a delete. `onDelete` gets `close`, to call when the request ends; a failure
 * shows `error` in the dialog so the reason is not lost. */
export function DeleteDialog({
  name,
  description,
  pending,
  error,
  open,
  onOpenChange,
  onDelete,
}: {
  name: string;
  description: string;
  pending: boolean;
  error?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDelete: (close: () => void) => void;
}) {
  return (
    <ConfirmDialog
      title={`Delete ${name}?`}
      description={description}
      action="Delete"
      cancel="Keep"
      destructive
      pending={pending}
      error={error}
      open={open}
      onOpenChange={onOpenChange}
      onConfirm={onDelete}
    />
  );
}

/** A Delete button that asks first. `onDelete` gets `close`, to call when the request ends,
 * so a failure closes the question and its message shows in the dialog behind it. */
export function DeleteConfirm({
  name,
  description,
  pending,
  label = "Delete",
  onDelete,
}: {
  name: string;
  description: string;
  pending: boolean;
  label?: string;
  onDelete: (close: () => void) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        className="text-destructive sm:mr-auto"
        onClick={() => setOpen(true)}
      >
        {label}
      </Button>
      <DeleteDialog
        name={name}
        description={description}
        pending={pending}
        open={open}
        onOpenChange={setOpen}
        onDelete={onDelete}
      />
    </>
  );
}

export function DiscardConfirm({
  subject,
  open,
  onOpenChange,
  onDiscard,
}: {
  subject: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDiscard: () => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Discard changes?</AlertDialogTitle>
          <AlertDialogDescription>
            Your changes to this {subject} are not saved.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep editing</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={onDiscard}>
            Discard
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** Asks before ending a call. It closes once the request is accepted; a failure shows a toast. */
export function EndCallDialog({
  conversation,
  open,
  onOpenChange,
}: {
  conversation: { id: string; status: ConversationStatus };
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const end = useEndConversation(conversation.id);
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>End this conversation?</AlertDialogTitle>
          <AlertDialogDescription>
            {conversation.status === "queued"
              ? "It has not connected yet, so it will be cancelled."
              : "The caller hangs up and what was said so far is kept."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep going</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={end.isPending}
            onClick={() =>
              end.mutate(undefined, {
                onSuccess: () => {
                  onOpenChange(false);
                  toast.success("Ending the conversation");
                },
                onError: (error) =>
                  toast.error("Could not end the conversation", { description: error.message }),
              })
            }
          >
            {end.isPending && <Spinner />}
            End conversation
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
