import { when } from "@/lib/format";

export function Timestamp({ iso }: { iso: string }) {
  return <time dateTime={iso}>{when(iso)}</time>;
}
