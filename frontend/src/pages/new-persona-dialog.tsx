import { Sparkles } from "lucide-react";
import { type SubmitEvent, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useDraftPersona } from "@/lib/queries";
import type { PersonaDraft } from "@/lib/types";

/** What `/personas/new` gets in its location state when the person generated the persona. */
export interface GeneratedPersona {
  idea: string;
  draft: PersonaDraft;
}

const EXAMPLES = [
  "impatient caller in a hurry",
  "confused first-time caller",
  "polite student who speaks Hindi",
];

/** The first step of a new persona: a short line that a model turns into the whole form. */
export function NewPersonaDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const generate = useDraftPersona();
  const [idea, setIdea] = useState("");
  // isPending lags a render behind, so quick repeated Enter presses would each start a request.
  const sending = useRef(false);

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const line = idea.trim();
    if (sending.current || !line) return;
    sending.current = true;
    generate.mutate(line, {
      onSettled: () => {
        sending.current = false;
      },
      onSuccess: (draft) =>
        navigate("/personas/new", { state: { idea: line, draft } satisfies GeneratedPersona }),
    });
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !generate.isPending && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <form noValidate onSubmit={submit} className="grid gap-6">
          <DialogHeader>
            <DialogTitle>New persona</DialogTitle>
            <DialogDescription>
              Describe the caller in a few words. Yaksh writes the persona from it: behavior,
              language, voice and surroundings. You can change any of it before you save.
            </DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="persona-idea">Caller</FieldLabel>
            <Textarea
              id="persona-idea"
              rows={3}
              autoFocus
              maxLength={500}
              placeholder="angry senior woman on a noisy street, speaks Hindi"
              value={idea}
              readOnly={generate.isPending}
              aria-busy={generate.isPending}
              onChange={(e) => setIdea(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <Button
                  key={example}
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={generate.isPending}
                  onClick={() => setIdea(example)}
                >
                  {example}
                </Button>
              ))}
            </div>
            {generate.isError ? (
              <FieldError>{generate.error.message}</FieldError>
            ) : (
              <FieldDescription>
                Mood, age, how they talk, language, where they call from. What you leave out gets a
                default.
              </FieldDescription>
            )}
          </Field>
          <DialogFooter className="sm:justify-between">
            <Button
              type="button"
              variant="link"
              className="px-0"
              disabled={generate.isPending}
              onClick={() => navigate("/personas/new")}
            >
              Skip, create manually
            </Button>
            <Button type="submit" disabled={generate.isPending || !idea.trim()}>
              {generate.isPending ? <Spinner /> : <Sparkles />}
              Generate
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
