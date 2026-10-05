import type { AgentRule, LlmRule, PhraseRule } from "@/lib/types";

export const MAX_RULES = 20;

export const ROLE_TEXT: Record<AgentRule["role"], string> = {
  deciding: "Counts in the call's verdict",
  reporting: "Reports only",
};

export const NEW_LLM: LlmRule = {
  kind: "llm",
  key: "",
  name: "",
  gate: "agent_spoke",
  applies_when: "",
  pass_when: "",
  fail_when: "",
  not_a_failure: null,
  role: "reporting",
};

export const NEW_PHRASE: PhraseRule = {
  kind: "phrase",
  key: "",
  name: "",
  expects: "required",
  match: "phrase",
  value: "",
  where: "any_agent_turn",
  role: "reporting",
};

/** What a rule still needs, by field. The server checks a regular expression. */
export function ruleProblems(rule: AgentRule): Partial<Record<string, string>> {
  const problems: Partial<Record<string, string>> = {};
  if (!rule.name.trim()) problems.name = "Enter a name.";
  if (rule.kind === "llm") {
    for (const field of ["applies_when", "pass_when", "fail_when"] as const) {
      if (!rule[field].trim()) problems[field] = "Fill this in.";
    }
  } else if (!rule.value.trim()) {
    problems.value = "Enter what to look for.";
  } else if (rule.match === "phrase" && !/[\p{L}\p{N}]/u.test(rule.value)) {
    problems.value = "A phrase needs a word or a number.";
  }
  return problems;
}

/** The rules to save. A new rule gets a key from its name; a saved rule keeps its key, so its
 * results stay comparable when it is renamed. */
export function toRules(rules: AgentRule[]): AgentRule[] {
  const taken = new Set(rules.map((rule) => rule.key).filter(Boolean));
  return rules.map((rule) => {
    const trimmed = { ...rule, name: rule.name.trim() };
    if (trimmed.kind === "llm") {
      trimmed.applies_when = trimmed.applies_when.trim();
      trimmed.pass_when = trimmed.pass_when.trim();
      trimmed.fail_when = trimmed.fail_when.trim();
      trimmed.not_a_failure = trimmed.not_a_failure?.trim() || null;
    }
    if (trimmed.key) return trimmed;
    const base = slug(trimmed.name);
    let key = base;
    for (let n = 2; taken.has(key); n++) key = `${base.slice(0, 58)}-${n}`;
    taken.add(key);
    return { ...trimmed, key };
  });
}

function slug(name: string): string {
  const found = name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
  return found || "rule";
}
