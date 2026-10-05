import { AudioLines, Play, Plus, Square } from "lucide-react";
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
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useVoicePreview } from "@/hooks/use-voice-preview";
import { useVoices } from "@/lib/queries";
import { LANGUAGE_NAMES, type Voice } from "@/lib/types";
import { VoiceDialog } from "@/pages/voice-dialog";

export function VoicesPage() {
  const voices = useVoices();
  const preview = useVoicePreview();
  const [editing, setEditing] = useState<Voice | "new" | null>(null);
  const voice = editing === "new" ? undefined : (editing ?? undefined);
  const close = () => setEditing(null);

  return (
    <div className="grid gap-6">
      <div className="flex min-h-[30px] flex-wrap items-center gap-x-2 gap-y-4">
        <h1 className="mr-auto text-h3-500">Voices</h1>
        <Button size="sm" onClick={() => setEditing("new")}>
          <Plus />
          Add voice
        </Button>
      </div>
      {voices.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : voices.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load voices</AlertTitle>
          <AlertDescription>{voices.error.message}</AlertDescription>
        </Alert>
      ) : voices.data.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <AudioLines />
            </EmptyMedia>
            <EmptyTitle>No voices</EmptyTitle>
            <EmptyDescription>
              Add an ElevenLabs voice so that a persona can speak with it.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setEditing("new")}>
              <Plus />
              Add voice
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {voices.data.map((item) => {
            const settings = {
              provider: item.provider,
              id: item.provider_voice_id,
              speed: 1,
              stability: 0.5,
            };
            return (
              <li key={item.id}>
                <Card className="relative h-full transition-colors has-[[data-slot=card-link]:focus-visible]:ring-2 has-[[data-slot=card-link]:focus-visible]:ring-ring/50 hover:bg-hv1 has-[[data-slot=card-link]:active]:bg-muted/70">
                  <CardHeader>
                    <CardTitle>
                      <button
                        type="button"
                        data-slot="card-link"
                        onClick={() => setEditing(item)}
                        className="text-left outline-none after:absolute after:inset-0 after:rounded-[inherit]"
                      >
                        {item.name}
                      </button>
                    </CardTitle>
                    <CardDescription className="flex flex-wrap items-center gap-1.5">
                      {item.accent && <span className="mr-1 capitalize">{item.accent}</span>}
                      {item.gender && <GenderBadge gender={item.gender} />}
                      {item.builtin && <Badge>Built-in</Badge>}
                    </CardDescription>
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
                        onClick={() => preview.toggle(item.id, settings, item.languages[0])}
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
                  <CardContent className="flex flex-wrap gap-1.5">
                    {item.languages.map((language) => (
                      <Badge key={language}>{LANGUAGE_NAMES[language]}</Badge>
                    ))}
                  </CardContent>
                  {preview.error(item.id) && (
                    <CardContent className="relative z-10 text-p-400 text-destructive">
                      {preview.error(item.id)}
                    </CardContent>
                  )}
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {editing !== null && (
        <VoiceDialog key={voice?.id ?? "new"} voice={voice} preview={preview} onClosed={close} />
      )}
    </div>
  );
}
