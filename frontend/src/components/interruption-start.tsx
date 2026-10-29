import type { ReactNode } from "react";

import { ANSWER_START, PHRASE_START } from "@/lib/interruptions";
import type { Interruption } from "@/lib/types";

/** How a line starts and when it can play, in the words of the scenario dialog. The phrase
 * comes in as the caller shows it, for example with the values of a data set filled in. */
export function InterruptionStart({ line, phrase }: { line: Interruption; phrase: ReactNode }) {
  return (
    <>
      {line.agent_says === null ? (
        ANSWER_START
      ) : (
        <>
          {PHRASE_START} “{phrase}”
        </>
      )}
      {` · Wait ${line.after_s} s · From answer ${line.from_answer}`}
    </>
  );
}
