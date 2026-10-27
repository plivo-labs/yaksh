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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useVoicePreview } from "@/hooks/use-voice-preview";
import { useSettings, useVoices } from "@/lib/queries";
import { TTS_PROVIDERS, ttsProvider } from "@/lib/speech-providers";
import { LANGUAGE_NAMES, type Voice, type VoiceProvider } from "@/lib/types";

const ALL = "all";
const PROVIDER_ITEMS = [
  { value: ALL, label: "All providers" },
  ...TTS_PROVIDERS.map((provider) => ({ value: provider.value, label: provider.label })),
];
import { VoiceDialog } from "@/pages/voice-dialog";

export function VoicesPage() {
  const voices = useVoices();
  const settings = useSettings();
  const preview = useVoicePreview();
  const [shown, setShown] = useState<VoiceProvider | typeof ALL>(ALL);
  const listed = (voices.data ?? []).filter((item) => shown === ALL || item.provider === shown);
  const [editing, setEditing] = useState<Voice | "new" | null>(null);
  const voice = editing === "new" ? undefined : (editing ?? undefined);
  const close = () => setEditing(null);

  return (
    <div className="grid gap-6">
      <div className="flex min-h-[30px] flex-wrap items-center gap-x-2 gap-y-4">
        <h1 className="mr-auto text-h3-500">Voices</h1>
        <Select
          items={PROVIDER_ITEMS}
          value={shown}
          onValueChange={(next) =>
            next && setShown(TTS_PROVIDERS.find((item) => item.value === next)?.value ?? ALL)
          }
        >
          <SelectTrigger aria-label="Provider" size="sm" className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PROVIDER_ITEMS.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
            <EmptyDescription>Add a voice so that a persona can speak with it.</EmptyDescription>
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
          {listed.map((item) => {
            const provider = ttsProvider(item.provider);
            const keyless = settings.data !== undefined && !settings.data.secrets[provider.secret];
            const spoken = {
              provider: item.provider,
              id: item.provider_voice_id,
              speed: 1,
              stability: item.provider === "elevenlabs" ? 0.5 : null,
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
                      <Badge>{provider.label}</Badge>
                      {!provider.wordTimestamps && <Badge variant="warning">Sentence timing</Badge>}
                      {keyless && <Badge variant="danger">No key</Badge>}
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
                        disabled={keyless}
                        onClick={() => preview.toggle(item.id, spoken, item.languages[0])}
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
