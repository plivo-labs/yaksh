import type { ConversationSummary, DataSet, Fact } from "@/lib/types";

type Kind = "known_facts" | "agent_data";

const PLACEHOLDER = /\{\{([^{}]*)\}\}/g;

/** The text with its runs of spaces made one space, and none at the ends. */
export function collapsed(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/** How the server compares names and placeholders: spaces collapsed, lower case. */
export function normalized(text: string): string {
  return collapsed(text).toLowerCase();
}

export function defaultDataSetName(number: number): string {
  return `Data set ${number}`;
}

/** The next "Data set N" name that no data set has. */
export function nextDataSetName(dataSets: DataSet[]): string {
  const taken = new Set(dataSets.map((dataSet) => normalized(dataSet.name)));
  let number = dataSets.length + 1;
  while (taken.has(normalized(defaultDataSetName(number)))) number += 1;
  return defaultDataSetName(number);
}

/** A part of a text: plain words, or a `{{fact name}}` with the value it takes. */
export type Piece = { text: string } | { fact: string; value: string | null };

/** The text split at its placeholders, each with the value of the fact it names in these
 * facts, or null when no fact has that name. */
export function pieces(text: string, facts: Fact[]): Piece[] {
  const values = new Map(facts.map((fact) => [normalized(fact.name), fact.value]));
  const result: Piece[] = [];
  let at = 0;
  for (const match of text.matchAll(PLACEHOLDER)) {
    const start = match.index ?? 0;
    if (start > at) result.push({ text: text.slice(at, start) });
    const fact = match[1].trim();
    result.push({ fact, value: values.get(normalized(fact)) ?? null });
    at = start + match[0].length;
  }
  if (at < text.length) result.push({ text: text.slice(at) });
  return result;
}

/** The placeholders in the text that name no known fact. */
export function unknownPlaceholders(text: string, factNames: string[]): string[] {
  const known = new Set(factNames.map(normalized));
  return Array.from(text.matchAll(PLACEHOLDER), (match) => match[1].trim()).filter(
    (name) => !known.has(normalized(name)),
  );
}

/** Where a value is written as whole words, in any case and with any spaces between its
 * words. */
function valuePattern(value: string): RegExp {
  const words = collapsed(value)
    .split(" ")
    .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`(?<![\\p{L}\\p{N}])${words.join("\\s+")}(?![\\p{L}\\p{N}])`, "giu");
}

/** The plain text of the text, outside its placeholders, in pieces. */
function plainParts(text: string): string[] {
  return text.split(PLACEHOLDER).filter((_, index) => index % 2 === 0);
}

/** Values written in the text that change between the data sets, so the text is right for
 * one data set only: the value, the data set it comes from and the fact that holds it. */
export function fixedValues(
  text: string,
  dataSets: DataSet[],
): { value: string; dataSet: string; fact: string }[] {
  if (dataSets.length < 2) return [];
  const found: { value: string; dataSet: string; fact: string }[] = [];
  const plain = plainParts(text);
  dataSets[0].known_facts.forEach((fact, index) => {
    const values = dataSets.map((dataSet) => dataSet.known_facts[index]?.value ?? "");
    if (new Set(values.map(normalized)).size < 2) return;
    dataSets.forEach((dataSet, at) => {
      const value = values[at].trim();
      if (value.length >= 3 && plain.some((part) => valuePattern(value).test(part)))
        found.push({ value, dataSet: dataSet.name, fact: fact.name });
    });
  });
  return found;
}

/** The name of the data set a conversation played, when its scenario version held more than
 * one; else null, since the name tells nothing apart. */
export function playedDataSet(
  conversation: Pick<ConversationSummary, "data_set_name" | "scenario_data_sets">,
): string | null {
  return conversation.scenario_data_sets > 1 ? conversation.data_set_name : null;
}

/** Rows whose name and values are all empty are dropped, in every data set alike. */
export function trimmedDataSets(dataSets: DataSet[]): DataSet[] {
  const kept = (kind: Kind) =>
    dataSets[0][kind]
      .map((_, row) => row)
      .filter((row) =>
        dataSets.some(
          (dataSet) => dataSet[kind][row].name.trim() || dataSet[kind][row].value.trim(),
        ),
      );
  const rows = { known_facts: kept("known_facts"), agent_data: kept("agent_data") };
  /** The names live on the first data set; the others follow it. */
  const pick = (dataSet: DataSet, kind: Kind): Fact[] =>
    rows[kind].map((row) => ({
      name: dataSets[0][kind][row].name.trim(),
      value: dataSet[kind][row].value.trim(),
    }));
  return dataSets.map((dataSet) => ({
    ...dataSet,
    name: dataSet.name.trim(),
    known_facts: pick(dataSet, "known_facts"),
    agent_data: pick(dataSet, "agent_data"),
  }));
}

/** What keeps the data sets from saving, or null. */
export function dataSetsProblem(dataSets: DataSet[]): string | null {
  const names = dataSets.map((dataSet) => normalized(dataSet.name));
  if (names.some((name) => !name)) return "Give each data set a name.";
  if (new Set(names).size < names.length) return "Give each data set a different name.";
  for (const kind of ["known_facts", "agent_data"] as const) {
    for (const [row, fact] of dataSets[0][kind].entries()) {
      const values = dataSets.map((dataSet) => dataSet[kind][row].value);
      if (!fact.name || values.some((value) => !value))
        return kind === "known_facts"
          ? "Give each fact a name and a value in every data set."
          : "Give each agent data item a name and a value in every data set.";
    }
  }
  return null;
}

/** The text with every writing of the value, outside its placeholders, replaced by the fact's
 * placeholder: the same matches fixedValues finds. */
export function withPlaceholder(text: string, value: string, fact: string): string {
  return text
    .split(/(\{\{[^{}]*\}\})/)
    .map((part, index) =>
      index % 2 === 1 ? part : part.replace(valuePattern(value), () => `{{${fact}}}`),
    )
    .join("");
}
