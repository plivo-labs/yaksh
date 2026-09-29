import { useState } from "react";

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
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {name}?</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel>Keep</AlertDialogCancel>
          <AlertDialogAction disabled={pending} onClick={() => onDelete(() => onOpenChange(false))}>
            {pending && <Spinner />}
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
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
          <AlertDialogAction onClick={onDiscard}>Discard</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
