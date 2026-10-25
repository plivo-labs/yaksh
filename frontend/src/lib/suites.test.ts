import { expect, test } from "bun:test";

import { cardsFrom } from "@/lib/suites";
import type { Persona, Scenario } from "@/lib/types";

function scenario(id: string, personaId: string, dataSets: string[]): Scenario {
  return {
    id,
    name: `Scenario ${id}`,
    persona_id: personaId,
    data_sets: dataSets.map((dataSet) => ({ id: dataSet, name: `Data set ${dataSet}` })),
  } as Scenario;
}

const persona = (id: string) => ({ id, name: `Persona ${id}` }) as Persona;

test("a copy leaves out what was deleted, counts it, and keeps a card that lost every persona", () => {
  const { rows, lost } = cardsFrom(
    [
      {
        scenario_id: "s1",
        persona_ids: ["p1", "p2"],
        data_set_ids: ["d0"],
        answered_by: ["caller", "voicemail"],
      },
      { scenario_id: "s2", persona_ids: ["p1"], data_set_ids: null },
      { scenario_id: "s3", persona_ids: ["p2"], data_set_ids: ["d1", "d2"] },
    ],
    [scenario("s1", "p1", ["d0"]), scenario("s3", "p1", ["d1"])],
    [persona("p1")],
  );

  expect(rows.map((row) => [row.scenario.id, row.personaIds, row.dataSetIds, row.answers])).toEqual(
    [
      ["s1", ["p1"], ["d0"], ["caller", "voicemail"]],
      ["s3", [], ["d1"], ["caller"]],
    ],
  );
  expect(lost).toEqual(["1 scenario", "1 persona", "1 data set"]);
});
