import { Badge } from "@/components/ui/badge";
import type { VoiceGender } from "@/lib/types";

export function GenderBadge({ gender }: { gender: VoiceGender }) {
  return <Badge className="capitalize">{gender}</Badge>;
}
