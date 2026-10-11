/** The words of one kind of draft: forks of a scenario, or data sets. */
export interface DraftWords {
  title: string;
  /** The name of one draft and of several, such as "fork" and "forks". */
  one: string;
  many: string;
  /** The stream's event that carries a draft. */
  event: string;
  placeholder: string;
  /** The save button's verb, such as "Save" or "Add". */
  verb: string;
}

export function forkWords(kind: "scenario" | "persona"): DraftWords {
  return {
    title: kind === "scenario" ? "Fork scenario" : "Fork persona",
    one: "fork",
    many: "forks",
    event: "fork",
    placeholder:
      kind === "scenario"
        ? "Describe a different change for each fork: what the caller does, or what the agent must do. For example: the caller also wants storage; the caller asks for a price on the call. To change only names, places or dates, add data sets instead."
        : "Describe enough different changes for each fork, and what the agent should do if that changes. For example: moves to China, Spain and Toronto; the agent should refuse.",
    verb: "Save",
  };
}
