import { Play, Plus, Square, UserRound } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

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
import { useSurroundingsPreview } from "@/hooks/use-surroundings-preview";
import { surroundingsLabel } from "@/lib/format";
import { usePersonas } from "@/lib/queries";
import { LANGUAGE_NAMES } from "@/lib/types";
import { NewPersonaDialog } from "@/pages/new-persona-dialog";

export function PersonasPage() {
  const personas = usePersonas();
  const preview = useSurroundingsPreview();
  const [creating, setCreating] = useState(false);

  return (
    <div className="grid gap-6">
      <div className="flex min-h-[30px] flex-wrap items-center gap-x-2 gap-y-4">
        <h1 className="mr-auto text-h3-500">Personas</h1>
        <Button size="sm" onClick={() => setCreating(true)}>
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
            <EmptyDescription>
              A persona is the caller that Yaksh plays: how it behaves and which voice it uses.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setCreating(true)}>
              <Plus />
              New persona
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {personas.data.map((item) => (
            <li key={item.id}>
              <Card className="relative h-full transition-colors has-[[data-slot=card-link]:focus-visible]:ring-2 has-[[data-slot=card-link]:focus-visible]:ring-ring/50 hover:bg-hv1 has-[[data-slot=card-link]:active]:bg-muted/70">
                <CardHeader>
                  <CardTitle>
                    <Link
                      to={`/personas/${item.id}`}
                      data-slot="card-link"
                      className="text-left outline-none after:absolute after:inset-0 after:rounded-[inherit]"
                    >
                      {item.name}
                    </Link>
                  </CardTitle>
                  <CardDescription className="flex flex-wrap items-center gap-1.5">
                    <span className="mr-1">{LANGUAGE_NAMES[item.language]}</span>
                    {item.voice_gender && <GenderBadge gender={item.voice_gender} />}
                    {item.builtin_key && <Badge>Built-in</Badge>}
                    {surroundingsLabel(item.surroundings) && (
                      <Badge>{surroundingsLabel(item.surroundings)}</Badge>
                    )}
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
                      onClick={() =>
                        preview.toggle(item.id, {
                          voice: item.voice,
                          language: item.language,
                          surroundings: item.surroundings,
                          sampleLine: item.sample_line,
                        })
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
                <CardContent className="line-clamp-3 text-p-400 text-muted-foreground">
                  {item.prompt}
                </CardContent>
                {preview.error(item.id) && (
                  <CardContent className="relative z-10 text-p-400 text-destructive">
                    {preview.error(item.id)}
                  </CardContent>
                )}
              </Card>
            </li>
          ))}
        </ul>
      )}
      {creating && <NewPersonaDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
