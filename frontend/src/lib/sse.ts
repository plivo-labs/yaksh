import { request } from "@/lib/api";

export interface ServerEvent {
  event: string;
  data: string;
}

/** Opens a server-sent event stream with the bearer token, which EventSource cannot send. A
 * refusal before the stream starts throws with the API's message. */
export function openStream(path: string, signal: AbortSignal, json?: unknown): Promise<Response> {
  return request(path, { method: json === undefined ? "GET" : "POST", json, signal });
}

export async function readEvents(
  response: Response,
  onEvent: (event: ServerEvent) => void,
): Promise<void> {
  if (!response.body) throw new Error("the stream has no body");
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

export async function subscribe(
  path: string,
  onEvent: (event: ServerEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  await readEvents(await openStream(path, signal), onEvent);
}
