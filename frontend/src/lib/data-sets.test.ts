import { expect, test } from "bun:test";

import {
  dataSetsProblem,
  fixedValues,
  pieces,
  trimmedDataSets,
  unknownPlaceholders,
  withPlaceholder,
} from "@/lib/data-sets";
import type { DataSet } from "@/lib/types";

const austin: DataSet = {
  name: "Austin",
  known_facts: [{ name: "Moving to", value: "Austin, Texas" }],
  agent_data: [],
};
const denver: DataSet = {
  name: "Denver",
  known_facts: [{ name: "Moving to", value: "Denver, Colorado" }],
  agent_data: [],
};

test("a placeholder takes the value of the fact it names, however it is spaced or cased", () => {
  expect(pieces("Move to {{ moving TO }} now", austin.known_facts)).toEqual([
    { text: "Move to " },
    { fact: "moving TO", value: "Austin, Texas" },
    { text: " now" },
  ]);
  expect(pieces("Ask for {{Zip}}", austin.known_facts)).toEqual([
    { text: "Ask for " },
    { fact: "Zip", value: null },
  ]);
  expect(unknownPlaceholders("{{Moving to}} and {{Zip}}", ["Moving to"])).toEqual(["Zip"]);
});

test("a value written for one data set is found, and replaced by its placeholder", () => {
  const text = "Reads back the move to Denver, Colorado.";
  expect(fixedValues(text, [austin, denver])).toEqual([
    { value: "Denver, Colorado", dataSet: "Denver", fact: "Moving to" },
  ]);
  expect(fixedValues(text, [denver])).toEqual([]);
  expect(fixedValues("Reads back {{Moving to}}.", [austin, denver])).toEqual([]);
  expect(withPlaceholder(text, "Denver, Colorado", "Moving to")).toBe(
    "Reads back the move to {{Moving to}}.",
  );
});

test("empty rows go from every data set alike, and a half-filled row keeps the save back", () => {
  const blank = { name: "", value: "" };
  const trimmed = trimmedDataSets([
    { ...austin, known_facts: [...austin.known_facts, blank] },
    { ...denver, known_facts: [...denver.known_facts, blank] },
  ]);
  expect(trimmed.map((dataSet) => dataSet.known_facts.length)).toEqual([1, 1]);
  expect(dataSetsProblem(trimmed)).toBeNull();
  const half = [austin, { ...denver, known_facts: [{ name: "Moving to", value: "" }] }];
  expect(dataSetsProblem(half)).toBe("Give each fact a name and a value in every data set.");
  expect(dataSetsProblem([austin, { ...denver, name: " austin" }])).toBe(
    "Give each data set a different name.",
  );
});

test("a replacement touches whole words outside placeholders only", () => {
  const text = "Austin and {{Austin office}}; Austinville, then austin   again.";
  expect(withPlaceholder(text, "Austin", "City")).toBe(
    "{{City}} and {{Austin office}}; Austinville, then {{City}}   again.",
  );
  expect(withPlaceholder("Moving to New  York", "New York", "$& city")).toBe(
    "Moving to {{$& city}}",
  );
  const sets = [{ ...austin, known_facts: [{ name: "Moving to", value: "New York" }] }, denver];
  expect(fixedValues("Moving to new   york.", sets)).toEqual([
    { value: "New York", dataSet: "Austin", fact: "Moving to" },
  ]);
  expect(fixedValues("See {{New York}} only.", sets)).toEqual([]);
});

test("names compare in lower case with their spaces collapsed, as the server compares them", () => {
  expect(unknownPlaceholders("{{ MOVING   to }}", ["Moving to"])).toEqual([]);
  expect(unknownPlaceholders("{{STRASSE}}", ["Straße"])).toEqual(["STRASSE"]);
});
