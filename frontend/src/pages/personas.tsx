import { Play, Plus, Square, UserRound } from "lucide-react";
import { useState } from "react";

import { GenderBadge } from "@/components/gender-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Empty, EmptyContent, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useVoicePreview } from "@/hooks/use-voice-preview";
import { noiseLabel } from "@/lib/format";
import { usePersonas } from "@/lib/queries";
import { LANGUAGE_NAMES, type Persona } from "@/lib/types";
import { PersonaDialog } from "@/pages/persona-dialog";

export function PersonasPage() {
  const personas = usePersonas();
  const preview = useVoicePreview();
  const [editing, setEditing] = useState<Persona | "new" | null>(null);
  const persona = editing === "new" ? undefined : (editing ?? undefined);
  const close = () => setEditing(null);

  return (
    <div className="grid gap-6">
      <div className="flex items-start justify-between gap-4">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Personas</h1>
        <Button onClick={() => setEditing("new")}>
          <Plus />
          New persona
        </Button>
      </div>
      {personas.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      ) : personas.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load personas</AlertTitle>
          <AlertDescription>{personas.error.message}</AlertDescription>
        </Alert>
      ) : personas.data.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <UserRound />
            </EmptyMedia>
            <EmptyTitle>No personas</EmptyTitle>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" onClick={() => setEditing("new")}>
              Create a persona
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {personas.data.map((item) => (
            <li key={item.id}>
              <Card className="relative h-full transition-colors has-[[data-slot=card-link]:focus-visible]:ring-2 has-[[data-slot=card-link]:focus-visible]:ring-ring/50 hover:bg-muted/40">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <button
                      type="button"
                      data-slot="card-link"
                      onClick={() => setEditing(item)}
                      className="text-left outline-none after:absolute after:inset-0 after:rounded-[inherit]"
                    >
                      {item.name}
                    </button>
                    {item.voice_gender && <GenderBadge gender={item.voice_gender} />}
                    {item.builtin_key && <Badge variant="secondary">Built-in</Badge>}
                    {noiseLabel(item.background_noise) && (
                      <Badge variant="outline">{noiseLabel(item.background_noise)}</Badge>
                    )}
                  </CardTitle>
                  <CardDescription>{LANGUAGE_NAMES[item.language]}</CardDescription>
                  <CardAction>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon-sm"
                      className="relative z-10"
                      aria-label={
                        preview.isPlaying(item.id) ? `Stop ${item.name}` : `Play ${item.name}`
                      }
                      aria-busy={preview.isLoading(item.id)}
                      onClick={() =>
                        preview.toggle(item.id, item.voice, item.language, item.background_noise)
                      }
                    >
                      {preview.isLoading(item.id) ? (
                        <Spinner />
                      ) : preview.isPlaying(item.id) ? (
                        <Square />
                      ) : (
                        <Play />
                      )}
                    </Button>
                  </CardAction>
                </CardHeader>
                <CardContent className="line-clamp-3 text-sm text-muted-foreground">
                  {item.prompt}
                </CardContent>
                {preview.error(item.id) && (
                  <CardContent className="relative z-10 text-sm text-destructive">
                    {preview.error(item.id)}
                  </CardContent>
                )}
              </Card>
            </li>
          ))}
        </ul>
      )}

      {editing !== null && (
        <PersonaDialog
          key={persona?.id ?? "new"}
          persona={persona}
          preview={preview}
          onClosed={close}
        />
      )}
    </div>
  );
}
