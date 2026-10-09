import { ArrowLeft, FileJson } from "lucide-react";
import { type SubmitEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";

import { DiscardConfirm } from "@/components/confirm-dialogs";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Panel, PanelHeader } from "@/components/panel";
import { StepFooter } from "@/components/step-footer";
import { type Step, Steps } from "@/components/steps";
import { Button } from "@/components/ui/button";
import { FieldDescription, FieldError, FieldGroup } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { useDraftKnowledgeBase } from "@/hooks/use-knowledge-base";
import { APPEAR, STEP_BACK, STEP_FORWARD } from "@/lib/motion";
import { useSaveAgent } from "@/lib/queries";
import { NEW_LLM, NEW_PHRASE, ruleProblems, toRules, withRule } from "@/lib/rules";
import type { AgentRule } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAgentDraft } from "@/hooks/use-agent-draft";
import { useBriefDraft } from "@/hooks/use-brief-draft";
import { CONTEXT_NOTE, EMPTY_DRAFT, toInput } from "@/lib/agent-draft";
import {
  clearStoredDraft,
  IMPORT_SOURCES,
  type ImportedFrom,
  readStoredDraft,
  type StoredDraft,
  writeStoredDraft,
} from "@/lib/new-agent-draft";
import {
  AgentIdField,
  CallOptionsFields,
  ContextFields,
  NameField,
  ReachChoice,
  ReachFields,
} from "@/pages/agent-form";
import { KnowledgeBasePanel } from "@/pages/agent-knowledge-base";
import { DraftRules, type RuleEdit } from "@/pages/agent-wizard-rules";

const STEPS: Step[] = [
  { label: "Agent", hint: "What it is and does" },
  { label: "Calls", hint: "How Yaksha reaches it" },
  { label: "Knowledge base", hint: "Optional" },
  { label: "Rules", hint: "Optional" },
];

/** The address of another step; the other parameters, such as an open rule, stay. */
function withStep(params: URLSearchParams, step: number) {
  const next = new URLSearchParams(params);
  next.set("step", String(step));
  return next;
}

/** Adds an agent in four steps. Nothing is saved until "Add agent", which sends the fields, the
 * knowledge base and the rules in one request and opens the new agent. The step is in the address,
 * and a step after one with problems opens that one instead. */
export function AgentWizardPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [stored] = useState(readStoredDraft);
  const form = useAgentDraft(EMPTY_DRAFT, stored?.draft);
  const [rules, setRules] = useState<AgentRule[]>(stored?.rules ?? []);
  const [ruleDraft, setRuleDraft] = useState(stored?.openRule ?? null);
  const importedFrom = stored?.importedFrom ?? null;
  const [briefDraftId, setBriefDraftId] = useState(stored?.briefDraftId ?? null);
  const briefDone = useCallback(() => setBriefDraftId(null), []);
  const brief = useBriefDraft(form, briefDraftId, briefDone);
  const save = useSaveAgent();
  const saving = save.isPending;
  const knowledgeBase = useDraftKnowledgeBase(save.isPending, stored?.documents);
  const uploading = knowledgeBase.progress !== null;
  /** Set once the draft is added or discarded, so leaving the page is no longer guarded. */
  const done = useRef(false);

  const { needs } = form;
  const stepProblems = [
    needs.name || needs.brief || needs.config,
    needs.direction || needs.reach,
    false,
    false,
  ];
  const furthest = stepProblems.indexOf(true) + 1 || STEPS.length;
  const requested = Number(params.get("step"));
  // While the agent is being added the wizard stays on the last step, so nothing changes under
  // the request.
  const step = saving
    ? STEPS.length
    : Number.isInteger(requested) && requested >= 1
      ? Math.min(requested, furthest)
      : 1;

  useEffect(() => {
    if (String(step) !== params.get("step")) setParams(withStep(params, step), { replace: true });
  }, [step, params, setParams]);

  /** The step on screen and the way it came in, so a step slides in from the side it follows. */
  const [shown, setShown] = useState({ step, motion: STEP_FORWARD });
  if (shown.step !== step) setShown({ step, motion: step > shown.step ? STEP_FORWARD : STEP_BACK });

  /** A new step takes the focus, so the keyboard and a screen reader start there. */
  const stepRef = useRef<HTMLDivElement>(null);
  const focusedStep = useRef(step);
  useEffect(() => {
    if (focusedStep.current === step) return;
    focusedStep.current = step;
    stepRef.current?.focus();
  }, [step]);

  const changed = form.dirty || rules.length > 0 || knowledgeBase.documents.length > 0;
  useEffect(() => {
    if (done.current) return;
    const kept: StoredDraft = {
      draft: form.draft,
      rules,
      documents: knowledgeBase.documents,
      openRule: ruleDraft,
      importedFrom,
      briefDraftId,
    };
    writeStoredDraft(kept);
  }, [form.draft, rules, knowledgeBase.documents, ruleDraft, importedFrom, briefDraftId]);

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      !done.current && changed && currentLocation.pathname !== nextLocation.pathname,
  );
  // Leaving while the agent is being added is held, and the save's result decides.
  useEffect(() => {
    if (saving && blocker.state === "blocked") blocker.reset();
  }, [saving, blocker]);

  const goTo = (next: number) => {
    form.hideErrors();
    setParams(withStep(params, next));
  };

  /** Changes one part of the address and keeps the rest. Setting a value adds a history entry, so
   * Back undoes it; removing one replaces the entry. */
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: value === null });
  };

  const ruleParam = params.get("rule");
  const ruleEdit = openRule(ruleParam, rules, ruleDraft);

  const continueFrom = (event: SubmitEvent<HTMLFormElement>, current: number) => {
    event.preventDefault();
    if (form.check(event.currentTarget, !stepProblems[current - 1])) goTo(current + 1);
  };

  // A complete rule left open in its form is added with the agent; an incomplete one holds it.
  const ruleComplete = ruleEdit !== null && Object.keys(ruleProblems(ruleEdit.rule)).length === 0;
  const ruleUnfinished = ruleEdit !== null && !ruleComplete;
  const add = () => {
    if (uploading || ruleUnfinished) return;
    const sent = ruleComplete ? withRule(rules, ruleEdit.index, ruleEdit.rule) : rules;
    const entries = knowledgeBase.documents.map(({ document_id, name }) => ({ document_id, name }));
    save.mutate(
      {
        ...toInput(form.draft),
        source: importedFrom ? IMPORT_SOURCES[importedFrom.kind] : "manual",
        knowledge_base: entries,
        rules: toRules(sent),
      },
      {
        onSuccess: (agent) => {
          done.current = true;
          clearStoredDraft();
          toast.success(`${agent.name} is added`);
          navigate(`/agents/${agent.id}`, { replace: true });
        },
      },
    );
  };

  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6">
      <div className="grid gap-1">
        <h1 className="text-h3-500">New agent</h1>
        <p className="text-p-400 text-muted-foreground">
          Tell Yaksha what the agent does, how to reach it and what every call must follow.
        </p>
      </div>
      <Steps
        steps={STEPS}
        current={step}
        href={(number) => `?${withStep(params, number)}`}
        locked={saving}
      />

      <div
        key={step}
        ref={stepRef}
        tabIndex={-1}
        aria-label={`Step ${step} of ${STEPS.length}: ${STEPS[step - 1].label}`}
        className={cn("flex flex-1 flex-col outline-none", shown.motion)}
      >
        {step === 1 && (
          <form
            noValidate
            onSubmit={(event) => continueFrom(event, 1)}
            className="flex flex-1 flex-col gap-6"
          >
            {importedFrom && <ImportedNote from={importedFrom} />}
            <Panel>
              <PanelHeader title="Agent" />
              <div className="grid gap-5 px-5 py-5">
                <p className="text-p-400 text-muted-foreground">{CONTEXT_NOTE}</p>
                <FieldGroup>
                  <NameField form={form} />
                  <ContextFields form={form} brief={brief} />
                  <AgentIdField form={form} />
                </FieldGroup>
              </div>
            </Panel>
            <StepFooter>
              <Button variant="ghost" nativeButton={false} render={<Link to="/agents/new" />}>
                <ArrowLeft />
                Back
              </Button>
              {brief.drafting && (
                <FieldDescription className={cn("ml-auto", APPEAR)}>
                  Wait for the brief.
                </FieldDescription>
              )}
              <Button type="submit" className="ml-auto" disabled={brief.drafting}>
                Continue
              </Button>
            </StepFooter>
          </form>
        )}

        {step === 2 && (
          <form
            noValidate
            onSubmit={(event) => continueFrom(event, 2)}
            className="flex flex-1 flex-col gap-6"
          >
            <Panel className="px-5 py-5">
              <FieldGroup>
                <ReachChoice form={form} />
                <ReachFields form={form} />
                <CallOptionsFields form={form} />
              </FieldGroup>
            </Panel>
            <StepFooter>
              <Button type="button" variant="ghost" onClick={() => goTo(1)}>
                <ArrowLeft />
                Back
              </Button>
              <Button type="submit" className="ml-auto">
                Continue
              </Button>
            </StepFooter>
          </form>
        )}

        {step === 3 && (
          <div className="flex flex-1 flex-col gap-6">
            <p className="text-p-400 text-muted-foreground">
              Optional. Yaksha reads these documents to write test scenarios, and the judges check
              the agent's statements against them. You can add documents later on the agent's Config
              tab.
            </p>
            <KnowledgeBasePanel source={knowledgeBase} />
            <StepFooter>
              <Button type="button" variant="ghost" onClick={() => goTo(2)}>
                <ArrowLeft />
                Back
              </Button>
              {uploading && (
                <FieldDescription className={cn("ml-auto", APPEAR)}>
                  Wait for the documents to finish uploading.
                </FieldDescription>
              )}
              <Button className="ml-auto" disabled={uploading} onClick={() => goTo(4)}>
                {knowledgeBase.documents.length === 0 ? "Skip" : "Continue"}
              </Button>
            </StepFooter>
          </div>
        )}

        {step === 4 && (
          <div className="flex flex-1 flex-col gap-6">
            <p className="text-p-400 text-muted-foreground">
              Optional. A rule is checked on every judged call of this agent, beside each scenario's
              criteria. You can add rules later on the agent's Config tab.
            </p>
            <DraftRules
              rules={rules}
              onChange={setRules}
              edit={ruleEdit}
              locked={saving}
              onEdit={(edit) => {
                setRuleDraft(null);
                setParam("rule", edit === null ? null : String(edit.index ?? edit.rule.kind));
              }}
              onRuleChange={(rule) =>
                !saving && ruleParam && setRuleDraft({ param: ruleParam, rule })
              }
            />
            <StepFooter>
              <Button type="button" variant="ghost" disabled={saving} onClick={() => goTo(3)}>
                <ArrowLeft />
                Back
              </Button>
              {save.error ? (
                <FieldError className="ml-auto">{save.error.message}</FieldError>
              ) : (
                (ruleUnfinished || uploading) && (
                  <FieldDescription className={cn("ml-auto", APPEAR)}>
                    {ruleUnfinished
                      ? "Finish the rule or cancel it first."
                      : "Wait for the documents to finish uploading."}
                  </FieldDescription>
                )
              )}
              <div className="ml-auto flex gap-2">
                {rules.length === 0 && !ruleEdit && (
                  <Button variant="ghost" disabled={saving || uploading} onClick={add}>
                    Skip rules
                  </Button>
                )}
                <Button disabled={saving || uploading || ruleUnfinished} onClick={add}>
                  {saving && <Spinner />}
                  Add agent
                </Button>
              </div>
            </StepFooter>
          </div>
        )}
      </div>

      <DiscardConfirm
        subject="agent"
        open={blocker.state === "blocked" && !saving}
        onOpenChange={(open) => !open && blocker.reset?.()}
        onDiscard={() => {
          done.current = true;
          clearStoredDraft();
          blocker.proceed?.();
        }}
      />
    </div>
  );
}

/** The rule form the address opens: `llm` or `phrase` for a new rule, or a rule's place in the
 * list, with the text typed into it so far. Anything else opens none. */
function openRule(
  param: string | null,
  rules: AgentRule[],
  typed: StoredDraft["openRule"],
): RuleEdit | null {
  const index = Number(param);
  const opened: RuleEdit | null =
    param === "llm"
      ? { index: null, rule: NEW_LLM }
      : param === "phrase"
        ? { index: null, rule: NEW_PHRASE }
        : param !== null && Number.isInteger(index) && rules[index]
          ? { index, rule: rules[index] }
          : null;
  return opened && typed?.param === param ? { ...opened, rule: typed.rule } : opened;
}

/** Where the draft came from, and what is left to fill in. */
const IMPORTED_NOTES: Record<ImportedFrom["kind"], string> = {
  file: "Check the drafted brief, then add the phone number in the next step.",
  "config-only": "The file is the config. Check the drafted brief, then fill in the rest.",
  "plivo-cx": "Check the drafted brief and the language.",
  elevenlabs: "Check the drafted brief.",
};

function ImportedNote({ from }: { from: ImportedFrom }) {
  return (
    <Alert role="status">
      <FileJson />
      <AlertTitle>Filled from {from.source}</AlertTitle>
      <AlertDescription>{IMPORTED_NOTES[from.kind]}</AlertDescription>
    </Alert>
  );
}
