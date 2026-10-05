import { Plus, Trash2 } from "lucide-react";

import { Segmented } from "@/components/segmented";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { MAX_RULES, NEW_LLM, NEW_PHRASE, ruleProblems } from "@/lib/rules";
import type { AgentRule, LlmRule, PhraseRule } from "@/lib/types";

/** The agent's rules: checks on every judged call, beside each scenario's criteria. */
export function RulesField({
  rules,
  onChange,
  submitted,
}: {
  rules: AgentRule[];
  onChange: (rules: AgentRule[]) => void;
  submitted: boolean;
}) {
  const replace = (index: number, rule: AgentRule) =>
    onChange(rules.map((current, at) => (at === index ? rule : current)));
  const full = rules.length >= MAX_RULES;
  return (
    <FieldGroup>
      {rules.map((rule, index) => (
        <RuleEditor
          key={index}
          id={`rule-${index}`}
          rule={rule}
          submitted={submitted}
          onChange={(next) => replace(index, next)}
          onRemove={() => onChange(rules.filter((_, at) => at !== index))}
        />
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={full}
          onClick={() => onChange([...rules, NEW_LLM])}
        >
          <Plus />
          LLM rule
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={full}
          onClick={() => onChange([...rules, NEW_PHRASE])}
        >
          <Plus />
          Phrase rule
        </Button>
        {full && <FieldDescription>An agent has at most {MAX_RULES} rules.</FieldDescription>}
      </div>
    </FieldGroup>
  );
}

function RuleEditor({
  id,
  rule,
  submitted,
  onChange,
  onRemove,
}: {
  id: string;
  rule: AgentRule;
  submitted: boolean;
  onChange: (rule: AgentRule) => void;
  onRemove: () => void;
}) {
  const problems = submitted ? ruleProblems(rule) : {};
  return (
    <div className="grid gap-5 rounded-md border px-4 py-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-s-500">{rule.kind === "llm" ? "LLM rule" : "Phrase rule"}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={`Remove ${rule.name || "this rule"}`}
          onClick={onRemove}
        >
          <Trash2 />
        </Button>
      </div>
      <Text
        id={`${id}-name`}
        label="Name"
        value={rule.name}
        maxLength={200}
        problem={problems.name}
        placeholder={rule.kind === "llm" ? "No promises about refunds" : "Says the clinic name"}
        onChange={(name) => onChange({ ...rule, name })}
      />
      {rule.kind === "llm" ? (
        <LlmFields id={id} rule={rule} problems={problems} onChange={onChange} />
      ) : (
        <PhraseFields id={id} rule={rule} problems={problems} onChange={onChange} />
      )}
      <Field orientation="horizontal">
        <FieldContent>
          <FieldLabel htmlFor={`${id}-role`}>Counts in the call's verdict</FieldLabel>
          <FieldDescription>When off, the rule only reports.</FieldDescription>
        </FieldContent>
        <Switch
          id={`${id}-role`}
          checked={rule.role === "deciding"}
          onCheckedChange={(checked) =>
            onChange({ ...rule, role: checked ? "deciding" : "reporting" })
          }
        />
      </Field>
    </div>
  );
}

function LlmFields({
  id,
  rule,
  problems,
  onChange,
}: {
  id: string;
  rule: LlmRule;
  problems: Partial<Record<string, string>>;
  onChange: (rule: LlmRule) => void;
}) {
  return (
    <>
      <Segmented
        label="Judged on"
        value={rule.gate}
        options={[
          { value: "agent_spoke", label: "Calls where the agent spoke" },
          { value: "always", label: "Every call" },
        ]}
        onChange={(gate) => onChange({ ...rule, gate })}
      />
      <Text
        id={`${id}-applies`}
        label="Applies when"
        long
        value={rule.applies_when}
        problem={problems.applies_when}
        placeholder="The caller asks for a refund."
        onChange={(applies_when) => onChange({ ...rule, applies_when })}
      />
      <Text
        id={`${id}-pass`}
        label="Passes when"
        long
        value={rule.pass_when}
        problem={problems.pass_when}
        placeholder="The agent says a person from billing will call back."
        onChange={(pass_when) => onChange({ ...rule, pass_when })}
      />
      <Text
        id={`${id}-fail`}
        label="Fails when"
        long
        value={rule.fail_when}
        problem={problems.fail_when}
        placeholder="The agent promises a refund or an amount."
        onChange={(fail_when) => onChange({ ...rule, fail_when })}
      />
      <Text
        id={`${id}-not`}
        label="Not a failure"
        long
        value={rule.not_a_failure ?? ""}
        placeholder="Optional. Saying the refund policy in general terms."
        onChange={(text) => onChange({ ...rule, not_a_failure: text })}
      />
    </>
  );
}

function PhraseFields({
  id,
  rule,
  problems,
  onChange,
}: {
  id: string;
  rule: PhraseRule;
  problems: Partial<Record<string, string>>;
  onChange: (rule: PhraseRule) => void;
}) {
  return (
    <>
      <div className="flex flex-wrap gap-x-6 gap-y-4">
        <Segmented
          label="The agent"
          value={rule.expects}
          options={[
            { value: "required", label: "Must say" },
            { value: "forbidden", label: "Must not say" },
          ]}
          onChange={(expects) => onChange({ ...rule, expects })}
        />
        <Segmented
          label="In"
          value={rule.where}
          options={[
            { value: "any_agent_turn", label: "Any turn" },
            { value: "first_agent_turn", label: "Its first turn" },
          ]}
          onChange={(where) => onChange({ ...rule, where })}
        />
        <Segmented
          label="Match"
          value={rule.match}
          options={[
            { value: "phrase", label: "Phrase" },
            { value: "regex", label: "Regular expression" },
          ]}
          onChange={(match) => onChange({ ...rule, match })}
        />
      </div>
      <Text
        id={`${id}-value`}
        label={rule.match === "phrase" ? "Phrase" : "Pattern"}
        value={rule.value}
        maxLength={200}
        mono={rule.match === "regex"}
        problem={problems.value}
        placeholder={
          rule.match === "phrase" ? "Sunrise Dental" : "\\bthis call (is|may be) recorded\\b"
        }
        description={
          rule.match === "phrase"
            ? 'Matches as written, or with numbers, dates and times in one written form: "two thirty p.m." matches 2:30 pm.'
            : "Python regular expression syntax. It matches each agent turn in any case, as written and with numbers, dates and times in one written form."
        }
        onChange={(value) => onChange({ ...rule, value })}
      />
    </>
  );
}

function Text({
  id,
  label,
  value,
  onChange,
  problem,
  placeholder,
  description,
  long = false,
  mono = false,
  maxLength = 1000,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  problem?: string;
  placeholder?: string;
  description?: string;
  long?: boolean;
  mono?: boolean;
  maxLength?: number;
}) {
  const shared = {
    id,
    value,
    maxLength,
    placeholder,
    "aria-invalid": Boolean(problem),
    "aria-describedby": problem ? `${id}-error` : undefined,
    className: mono ? "font-mono text-xs" : undefined,
  };
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {long ? (
        <Textarea rows={2} {...shared} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <Input {...shared} onChange={(e) => onChange(e.target.value)} />
      )}
      {description && <FieldDescription>{description}</FieldDescription>}
      {problem && <FieldError id={`${id}-error`}>{problem}</FieldError>}
    </Field>
  );
}
