import { Badge } from "@/components/ui/badge";
import type { VoiceGender } from "@/lib/types";

export function GenderBadge({ gender }: { gender: VoiceGender }) {
  return (
    <Badge variant="outline" className="capitalize">
      {gender}
    </Badge>
  );
}
