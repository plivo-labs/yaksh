import { Segmented } from "@/components/segmented";
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
import { ruleProblems } from "@/lib/rules";
import type { AgentRule, LlmRule, PhraseRule } from "@/lib/types";

/** One rule's fields. The kind is chosen when the rule is added and does not change. */
export function RuleFields({
  rule,
  submitted,
  onChange,
}: {
  rule: AgentRule;
  submitted: boolean;
  onChange: (rule: AgentRule) => void;
}) {
  const problems = submitted ? ruleProblems(rule) : {};
  return (
    <FieldGroup>
      <Text
        id="rule-name"
        label="Name"
        value={rule.name}
        maxLength={200}
        problem={problems.name}
        placeholder={rule.kind === "llm" ? "No promises about refunds" : "Says the clinic name"}
        onChange={(name) => onChange({ ...rule, name })}
      />
      {rule.kind === "llm" ? (
        <LlmFields rule={rule} problems={problems} onChange={onChange} />
      ) : (
        <PhraseFields rule={rule} problems={problems} onChange={onChange} />
      )}
      <Field orientation="horizontal" className="rounded-md border bg-muted/40 px-3.5 py-3">
        <FieldContent>
          <FieldLabel htmlFor="rule-role">Counts in the call's verdict</FieldLabel>
          <FieldDescription>When off, the rule only reports.</FieldDescription>
        </FieldContent>
        <Switch
          id="rule-role"
          checked={rule.role === "deciding"}
          onCheckedChange={(checked) =>
            onChange({ ...rule, role: checked ? "deciding" : "reporting" })
          }
        />
      </Field>
    </FieldGroup>
  );
}

function LlmFields({
  rule,
  problems,
  onChange,
}: {
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
        id="rule-applies"
        label="Applies when"
        long
        value={rule.applies_when}
        problem={problems.applies_when}
        placeholder="The caller asks for a refund."
        onChange={(applies_when) => onChange({ ...rule, applies_when })}
      />
      <Text
        id="rule-pass"
        label="Passes when"
        long
        value={rule.pass_when}
        problem={problems.pass_when}
        placeholder="The agent says a person from billing will call back."
        onChange={(pass_when) => onChange({ ...rule, pass_when })}
      />
      <Text
        id="rule-fail"
        label="Fails when"
        long
        value={rule.fail_when}
        problem={problems.fail_when}
        placeholder="The agent promises a refund or an amount."
        onChange={(fail_when) => onChange({ ...rule, fail_when })}
      />
      <Text
        id="rule-not"
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
  rule,
  problems,
  onChange,
}: {
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
        id="rule-value"
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
    className: mono ? "font-mono text-xs-400" : undefined,
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
