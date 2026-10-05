// Plays a live call's audio from GET /conversations/{id}/listen: the agent on the left, the
// caller on the right, about half a second behind the call.
import { openStream } from "@/lib/sse";

const RATE = 8000;
const LENGTH_BYTES = 4;
const HEADER_BYTES = 9;
/** How far behind the fastest delivery the audio plays: room for network jitter. */
const DELAY_S = 0.4;
/** How far behind its place a side may play, after a burst, before it skips audio. */
const MAX_BEHIND_S = 0.3;
/** How close to its place a skipping side comes before it plays again. A side further behind
 * than this drops its quiet chunks, so it catches up in the pauses. */
const CAUGHT_UP_S = 0.05;
/** Below this RMS a chunk is a pause, about -40 dBFS. */
const QUIET_RMS = 0.01;
const LATE_S = 0.02;
/** How long chunks may all arrive late before the delay is measured again. */
const LATE_LIMIT_S = 0.5;

interface Chunk {
  side: number;
  atS: number;
  samples: Float32Array<ArrayBuffer>;
}

function parse(message: Uint8Array<ArrayBuffer>): Chunk {
  const view = new DataView(message.buffer, message.byteOffset, message.byteLength);
  const pcm = new Int16Array(message.slice(HEADER_BYTES).buffer);
  const samples = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) samples[i] = pcm[i] / 32768;
  return { side: view.getUint8(0), atS: view.getFloat64(1, true) / 1000, samples };
}

function rms(samples: Float32Array): number {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.sqrt(sum / samples.length);
}

/** Where each chunk plays on the AudioContext's clock: its place on the call's timeline, a fixed
 * delay after the fastest delivery so far. A late chunk is dropped, and after LATE_LIMIT_S of
 * late chunks the delay is measured again. A side that falls more than MAX_BEHIND_S behind its
 * place, after a burst, skips audio until it is within CAUGHT_UP_S, so both sides stay on one
 * timeline; arrival jitter below that loses no audio. */
class Timeline {
  private offset = Number.POSITIVE_INFINITY;
  private lateS = 0;
  private readonly next = [0, 0];
  private readonly skipping = [false, false];

  place(chunk: Chunk, now: number): number | null {
    const duration = chunk.samples.length / RATE;
    this.offset = Math.min(this.offset, now - chunk.atS);
    const target = chunk.atS + this.offset + DELAY_S;
    if (target < now + LATE_S) {
      this.lateS += duration;
      if (this.lateS > LATE_LIMIT_S) {
        this.offset = Number.POSITIVE_INFINITY;
        this.lateS = 0;
      }
      return null;
    }
    this.lateS = 0;
    const when = Math.max(target, this.next[chunk.side]);
    const behind = when - target;
    if (behind > MAX_BEHIND_S) this.skipping[chunk.side] = true;
    if (this.skipping[chunk.side] && behind > CAUGHT_UP_S) return null;
    this.skipping[chunk.side] = false;
    if (behind > CAUGHT_UP_S && rms(chunk.samples) < QUIET_RMS) return null;
    this.next[chunk.side] = when + duration;
    return when;
  }
}

/** The complete messages at the front of a stream's bytes, and the bytes left after them. */
function unframe(
  bytes: Uint8Array<ArrayBuffer>,
): [Uint8Array<ArrayBuffer>[], Uint8Array<ArrayBuffer>] {
  const messages = [];
  let offset = 0;
  while (bytes.length - offset >= LENGTH_BYTES) {
    const size = new DataView(bytes.buffer, bytes.byteOffset + offset).getUint32(0, true);
    if (bytes.length - offset - LENGTH_BYTES < size) break;
    messages.push(bytes.slice(offset + LENGTH_BYTES, offset + LENGTH_BYTES + size));
    offset += LENGTH_BYTES + size;
  }
  return [messages, bytes.slice(offset)];
}

/** Resolves after that many seconds, or at once when the signal aborts. */
function until(seconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, Math.max(0, seconds) * 1000);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/** Plays the call until it ends or the signal aborts. The page must call this from a click,
 * because browsers start audio only after a user gesture. */
export async function listen(conversationId: string, signal: AbortSignal): Promise<void> {
  const context = new AudioContext({ sampleRate: RATE });
  const merger = context.createChannelMerger(2);
  merger.connect(context.destination);
  const timeline = new Timeline();
  let playedUntil = 0;
  try {
    await context.resume();
    const response = await openStream(`/conversations/${conversationId}/listen`, signal);
    if (!response.body) return;
    const reader = response.body.getReader();
    let pending = new Uint8Array(0);
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        await until(playedUntil - context.currentTime, signal);
        return;
      }
      const joined = new Uint8Array(pending.length + value.length);
      joined.set(pending);
      joined.set(value, pending.length);
      const [messages, rest] = unframe(joined);
      pending = rest;
      for (const message of messages) {
        const chunk = parse(message);
        const when = timeline.place(chunk, context.currentTime);
        if (when === null) continue;
        const buffer = context.createBuffer(1, chunk.samples.length, RATE);
        buffer.copyToChannel(chunk.samples, 0);
        const source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(merger, 0, chunk.side);
        source.start(when);
        playedUntil = Math.max(playedUntil, when + chunk.samples.length / RATE);
      }
    }
  } finally {
    await context.close();
  }
}
