import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { stamp } from "@/lib/format";
import { NOISE_SOUND_LABELS, type PlayedSound, SPEAKER_KIND_LABELS } from "@/lib/types";

function soundName(sound: PlayedSound): string {
  if (sound.speaker) return `Second speaker: ${SPEAKER_KIND_LABELS[sound.speaker]}`;
  return sound.sound ? NOISE_SOUND_LABELS[sound.sound] : sound.file;
}

/** The sounds a call played behind the caller, on the call's time line, and what a background
 * speaker said. Sounds planned after the call ended are left out: nobody heard them. */
export function CallSounds({ sounds, lengthS }: { sounds: PlayedSound[]; lengthS: number }) {
  const heard = sounds.filter((sound) => sound.start_s < lengthS);
  if (heard.length === 0) return null;
  const rows = new Map<string, PlayedSound[]>();
  for (const sound of heard) {
    const name = soundName(sound);
    rows.set(name, [...(rows.get(name) ?? []), sound]);
  }
  const lines = heard
    .flatMap((sound) => sound.speaker_lines)
    .filter((line) => line.at_s < lengthS)
    .sort((a, b) => a.at_s - b.at_s);
  const share = (seconds: number) => `${(Math.min(seconds, lengthS) / lengthS) * 100}%`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Behind the caller</CardTitle>
        <CardDescription>
          When each sound played, over the {stamp(lengthS)} of the call.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {[...rows].map(([name, played]) => (
          <div key={name} className="grid gap-1">
            <span className="text-s-500">{name}</span>
            <div className="relative h-2 rounded-full bg-muted" aria-hidden>
              {played.map((sound) => (
                <span
                  key={sound.start_s}
                  className="absolute inset-y-0 rounded-full bg-primary/60"
                  style={{
                    left: share(sound.start_s),
                    width: `calc(${share(sound.end_s ?? lengthS)} - ${share(sound.start_s)})`,
                  }}
                />
              ))}
            </div>
          </div>
        ))}
        {lines.length > 0 && (
          <div className="grid gap-1 pt-2">
            <span className="text-s-500">What the other person said</span>
            <ul className="grid gap-1 text-p-400">
              {lines.map((line) => (
                <li key={`${line.at_s}-${line.text}`} className="flex gap-3">
                  <span className="w-10 shrink-0 text-muted-foreground tabular-nums">
                    {stamp(line.at_s)}
                  </span>
                  <span>{line.text}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
