import { GitFork } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { ForkDialog } from "@/components/fork-dialog";
import { Button } from "@/components/ui/button";
import { surroundingsLabel } from "@/lib/format";
import {
  personaNames,
  useDeletePersona,
  useForkPersona,
  useSavePersona,
  useVoices,
} from "@/lib/queries";
import { LANGUAGE_NAMES, type Persona, type PersonaInput } from "@/lib/types";

function changed(label: string, from: string, to: string) {
  return (
    <>
      {label} <span className="line-through">{from}</span> → {to}
    </>
  );
}

/** Fork on a persona's page: Generate writes forks from an instruction; the manual path saves
 * an exact copy at once and opens it. */
export function PersonaFork({ persona }: { persona: Persona }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const fork = useForkPersona();
  const create = useSavePersona();
  const remove = useDeletePersona();
  const voices = useVoices();
  const voiceName = (id: string) =>
    voices.data?.find((voice) => voice.provider_voice_id === id)?.name ?? id;

  const forkManually = () =>
    fork.mutate(persona.id, {
      onSuccess: (copy) => {
        setOpen(false);
        navigate(`/personas/${copy.id}`);
        toast.success("Fork created", {
          description: `"${copy.name}" is a copy. Change what you need and save.`,
          action: {
            label: "Undo",
            onClick: () =>
              void remove.mutateAsync(copy.id).then(() => navigate(`/personas/${persona.id}`)),
          },
        });
      },
      onError: (error) => toast.error("Could not fork the persona", { description: error.message }),
    });

  const changes = (draft: PersonaInput) => {
    const lines = [];
    if (draft.language !== persona.language)
      lines.push(
        changed("Language", LANGUAGE_NAMES[persona.language], LANGUAGE_NAMES[draft.language]),
      );
    if (draft.voice.id !== persona.voice.id)
      lines.push(changed("Voice", voiceName(persona.voice.id), voiceName(draft.voice.id)));
    if (draft.voice.speed !== persona.voice.speed)
      lines.push(changed("Speed", String(persona.voice.speed), String(draft.voice.speed)));
    const before = surroundingsLabel(persona.surroundings, true) ?? "Quiet room";
    const after = surroundingsLabel(draft.surroundings, true) ?? "Quiet room";
    if (JSON.stringify(draft.surroundings) !== JSON.stringify(persona.surroundings))
      lines.push(changed("Surroundings", before, after));
    if (draft.prompt !== persona.prompt)
      lines.push(
        <details>
          <summary className="cursor-pointer">Behavior changed</summary>
          <p className="mt-1 whitespace-pre-line text-foreground">{draft.prompt}</p>
        </details>,
      );
    return lines;
  };

  return (
    <>
      <Button
        type="button"
        variant="outline"
        disabled={fork.isPending}
        onClick={() => setOpen(true)}
      >
        <GitFork />
        Fork
      </Button>
      {open && (
        <ForkDialog<PersonaInput>
          kind="persona"
          originalName={persona.name}
          path={`/personas/${persona.id}/forks/draft`}
          changes={changes}
          onManual={forkManually}
          takenNames={personaNames}
          saveOne={(draft) => create.mutateAsync(draft)}
          onSaved={(ids) =>
            toast.success(`Saved ${ids.length === 1 ? "1 fork" : `${ids.length} forks`}`)
          }
          onClosed={() => setOpen(false)}
        />
      )}
    </>
  );
}
