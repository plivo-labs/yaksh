import { playsScenario } from "@/lib/answering";
import { filledText } from "@/lib/data-sets";
import { clock } from "@/lib/format";
import {
  type Conversation,
  type DataSet,
  type Interruption,
  type InterruptionTry,
  MAX_LINE_CHARS,
  type Turn,
  type WireEvent,
} from "@/lib/types";

export const PHRASE_START = "When the agent says";
export const ANSWER_START = "When an answer starts";

/** The most words of the agent before a line that a note quotes, as the judges' note does. */
const QUOTED_WORDS = 12;

/** Letters, marks and decimal digits: what the API reads as a word or a number in a phrase. */
const WORD_OR_NUMBER = /[\p{L}\p{M}\p{Nd}]/u;

/** What keeps each field of a line from saving, as the API checks it; null when the field can
 * save. */
export function lineProblems(line: Interruption, dataSets: DataSet[]) {
  return {
    phrase: line.agent_says === null ? null : phraseProblem(line.agent_says, dataSets),
    wait:
      Number.isFinite(line.after_s) && line.after_s >= 0 && line.after_s <= 30
        ? null
        : "Enter a wait from 0 to 30 seconds.",
    answer:
      Number.isInteger(line.from_answer) && line.from_answer >= 1 && line.from_answer <= 100
        ? null
        : "Enter an answer from 1 to 100.",
    say: line.say.trim()
      ? lengthProblem("line", line.say, dataSets)
      : "Enter what the caller says.",
  };
}

export function lineSaves(line: Interruption, dataSets: DataSet[]): boolean {
  return Object.values(lineProblems(line, dataSets)).every((problem) => problem === null);
}

function phraseProblem(phrase: string, dataSets: DataSet[]): string | null {
  if (!phrase.trim()) return "Enter a phrase.";
  if (!WORD_OR_NUMBER.test(phrase)) return "Enter a phrase with a word or a number.";
  return lengthProblem("phrase", phrase, dataSets);
}

/** A line or a phrase stays within the limit as written and with the facts of each data set.
 * The API counts code points, so this does too. */
function lengthProblem(part: "line" | "phrase", text: string, dataSets: DataSet[]): string | null {
  const trimmed = text.trim();
  if ([...trimmed].length > MAX_LINE_CHARS) {
    return `Enter a ${part} of at most ${MAX_LINE_CHARS} characters.`;
  }
  const over = dataSets.find(
    (dataSet) => [...filledText(trimmed, dataSet.known_facts)].length > MAX_LINE_CHARS,
  );
  if (!over) return null;
  const facts = dataSets.length > 1 ? `the facts of ${over.name}` : "the known facts";
  return `With ${facts}, the ${part} is longer than ${MAX_LINE_CHARS} characters.`;
}

/** Why no line of the scenario could play on the conversation, or null when lines can play: the
 * API plays lines only on phone calls on which the persona talks. */
export function noLines(
  conversation: Pick<Conversation, "transport" | "answered_by" | "wire_events">,
): string | null {
  if (conversation.transport === "text") return "A text run has no interruptions.";
  if (!playsScenario(conversation.answered_by, conversation.wire_events)) {
    return "No caller talked on this call, so no line played.";
  }
  return null;
}

/** Where each interruption line played, by the index of the line's turn: how far into which
 * agent turn the caller said it. The agent turn is the one that holds the start of the agent's
 * turn when the line played, or else the line's start. With no such turn, the note quotes the
 * agent's words before the line; a line over sound with no words has neither. A line that the
 * agent heard only in part is two turns, and the note goes on the first. */
export function lineNotes(
  turns: Turn[],
  events: WireEvent[],
  connectedMs: number,
): Map<number, string> {
  const played = new Map<number, { at: number; attempt: InterruptionTry }>();
  for (const event of events) {
    const attempt = event.interruption;
    if (attempt && attempt.reason === null)
      played.set(attempt.number, { at: event.at_ms, attempt });
  }
  const notes = new Map<number, string>();
  turns.forEach((turn, index) => {
    const number = turn.interruption;
    const line = number ? played.get(number) : undefined;
    if (!number || !line) return;
    notes.set(index, note(turns, line.at, line.attempt, connectedMs));
    played.delete(number);
  });
  return notes;
}

function note(turns: Turn[], at: number, attempt: InterruptionTry, connectedMs: number): string {
  const agent = holding(turns, attempt.turn_started_ms) ?? holding(turns, at);
  if (agent) {
    const into = ((at - agent.started_at_ms) / 1000).toFixed(1);
    return `${into} s into the agent's turn at ${clock(Math.max(0, agent.started_at_ms - connectedMs))}`;
  }
  if (attempt.words) return `After the agent said “${lastWords(attempt.words)}”`;
  return "Over sound with no words from the agent";
}

function holding(turns: Turn[], ms: number | null): Turn | undefined {
  if (ms === null) return undefined;
  return turns.find(
    (turn) =>
      turn.role === "agent" &&
      turn.started_at_ms <= ms &&
      ms <= Math.max(turn.started_at_ms, turn.ended_at_ms),
  );
}

function lastWords(words: string): string {
  const split = words.split(/\s+/).filter(Boolean);
  return split.length <= QUOTED_WORDS
    ? split.join(" ")
    : `…${split.slice(-QUOTED_WORDS).join(" ")}`;
}
