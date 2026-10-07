import { Plus } from "lucide-react";
import { type SubmitEvent, useState } from "react";

import { Panel, PanelHeader } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { revealErrors } from "@/lib/forms";
import { REVEAL } from "@/lib/motion";
import {
  KIND,
  MAX_RULES,
  NEW_LLM,
  NEW_PHRASE,
  ROLE_TEXT,
  ruleProblems,
  withRule,
  summary,
} from "@/lib/rules";
import type { AgentRule } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RuleFields } from "@/pages/agent-rules-field";

/** The rule open in the inline form, as typed so far: a new one (`index` null) or the one at
 * `index`. */
export interface RuleEdit {
  index: number | null;
  rule: AgentRule;
}

/** The rules of an agent that does not exist yet. They stay in the wizard's draft and go with the
 * request that adds the agent. One rule is edited at a time, in a form above the list. */
export function DraftRules({
  rules,
  onChange,
  edit,
  onEdit,
  onRuleChange,
  locked,
}: {
  rules: AgentRule[];
  onChange: (rules: AgentRule[]) => void;
  edit: RuleEdit | null;
  onEdit: (edit: RuleEdit | null) => void;
  onRuleChange: (rule: AgentRule) => void;
  /** While the agent is being added, nothing here changes. */
  locked: boolean;
}) {
  const full = locked || edit !== null || rules.length >= MAX_RULES;
  const finish = (next: AgentRule[]) => {
    onChange(next);
    onEdit(null);
  };
  return (
    <Panel>
      <PanelHeader
        title="Rules"
        action={
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={full}
              onClick={() => onEdit({ index: null, rule: NEW_LLM })}
            >
              <Plus />
              LLM rule
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={full}
              onClick={() => onEdit({ index: null, rule: NEW_PHRASE })}
            >
              <Plus />
              Phrase rule
            </Button>
          </div>
        }
      />
      {edit && (
        <RuleForm
          key={edit.index ?? `new-${edit.rule.kind}`}
          rule={edit.rule}
          locked={locked}
          title={
            edit.index === null
              ? `New ${KIND[edit.rule.kind].label}`
              : `Edit ${rules[edit.index].name}`
          }
          onChange={onRuleChange}
          onSave={(rule) => finish(withRule(rules, edit.index, rule))}
          onRemove={
            edit.index === null
              ? undefined
              : () => finish(rules.filter((_, index) => index !== edit.index))
          }
          onCancel={() => onEdit(null)}
        />
      )}
      {rules.length === 0 ? (
        !edit && (
          <p className="px-5 py-8 text-center text-p-400 text-muted-foreground">
            No rules yet. Add an LLM rule for what the judge model should check, or a phrase rule
            for words the agent must or must not say.
          </p>
        )
      ) : (
        <ul className="divide-y">
          {rules.map((rule, index) => (
            // A draft rule has no key until the agent is added, so its place in the list names it.
            <li key={index}>
              <button
                type="button"
                disabled={locked || edit !== null}
                onClick={() => onEdit({ index, rule })}
                className="grid w-full min-w-0 gap-0.5 px-5 py-3 text-left outline-none transition-colors hover:bg-hv1 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset disabled:cursor-default disabled:hover:bg-transparent"
              >
                <span className="truncate text-s-500" title={rule.name}>
                  {rule.name}
                </span>
                <span className="truncate text-xs-400 text-muted-foreground">
                  {summary(rule)} · {ROLE_TEXT[rule.role]}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function RuleForm({
  rule,
  locked,
  title,
  onChange,
  onSave,
  onRemove,
  onCancel,
}: {
  rule: AgentRule;
  locked: boolean;
  title: string;
  onChange: (rule: AgentRule) => void;
  onSave: (rule: AgentRule) => void;
  /** Absent for a rule that is not in the list yet. */
  onRemove?: () => void;
  onCancel: () => void;
}) {
  const [submitted, setSubmitted] = useState(false);

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const valid = Object.keys(ruleProblems(rule)).length === 0;
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    onSave(rule);
  };

  return (
    <form
      noValidate
      aria-label={title}
      onSubmit={submit}
      className={cn("grid gap-5 border-b bg-muted/40 px-5 py-5", REVEAL)}
    >
      <div className="grid gap-0.5">
        <p className="text-p-500">{title}</p>
        <p className="text-s-400 text-muted-foreground">{KIND[rule.kind].note}</p>
      </div>
      <fieldset disabled={locked} className="contents">
        <RuleFields rule={rule} submitted={submitted} onChange={onChange} />
        <div className="flex flex-wrap items-center justify-end gap-2">
          {onRemove && (
            <Button type="button" variant="ghost" size="sm" className="mr-auto" onClick={onRemove}>
              Remove
            </Button>
          )}
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" size="sm">
            {onRemove ? "Save rule" : "Add rule"}
          </Button>
        </div>
      </fieldset>
    </form>
  );
}
