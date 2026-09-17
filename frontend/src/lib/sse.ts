import { authHeaders } from "@/lib/api";

export interface ServerEvent {
  event: string;
  data: string;
}

/** Reads a server-sent event stream with the bearer token, which EventSource cannot send. */
export async function subscribe(
  path: string,
  onEvent: (event: ServerEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1${path}`, { headers: authHeaders(), signal });
  if (!response.ok || !response.body) throw new Error(`${response.status} ${response.statusText}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let data: string[] = [];
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).replace(/\r$/, "");
      buffer = buffer.slice(newline + 1);
      if (line === "") {
        if (data.length) onEvent({ event, data: data.join("\n") });
        event = "message";
        data = [];
      } else if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        data.push(line.slice(5).replace(/^ /, ""));
      }
      newline = buffer.indexOf("\n");
    }
  }
}
