import { Plus } from "lucide-react";
import { Fragment, type SubmitEvent, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import { toast } from "sonner";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { ActionPanel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FieldError } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Explained, OutcomeCounts } from "@/components/verdict-ui";
import { useCloseGuard } from "@/hooks/use-close-guard";
import { when } from "@/lib/format";
import { revealErrors } from "@/lib/forms";
import { useRuleResults, useSaveRules } from "@/lib/queries";
import {
  KIND,
  MAX_RULES,
  NEW_LLM,
  NEW_PHRASE,
  ROLE_TEXT,
  ruleProblems,
  summary,
} from "@/lib/rules";
import type { Agent, AgentRule, RuleResults } from "@/lib/types";
import { RuleFields } from "@/pages/agent-rules-field";

const RESULTS_NOTE =
  "Over the judged calls that ran the rule as it is written now. A change to what a rule checks starts its results again. The judge model reads an LLM rule's name, so a new name starts an LLM rule's results again too. A change to whether a rule counts does not.";

/** The agent's rules with how each did, and the dialog that adds or edits one. A rule with no key
 * is not saved yet. An address that ends in `#rules` scrolls to the panel. */
export function AgentRules({ agent }: { agent: Agent }) {
  const results = useRuleResults(agent.id);
  const [editing, setEditing] = useState<AgentRule | null>(null);
  const full = agent.rules.length >= MAX_RULES;
  const panel = useRef<HTMLElement>(null);
  const { hash } = useLocation();
  useLayoutEffect(() => {
    if (hash === "#rules") panel.current?.scrollIntoView();
  }, [hash]);
  return (
    <ActionPanel
      ref={panel}
      title="Rules"
      className="scroll-mt-5"
      action={
        <>
          <p className="mr-auto max-w-prose text-s-400 text-muted-foreground">
            Checks on every judged call of this agent, beside each scenario's criteria.
            {full && ` An agent has at most ${MAX_RULES} rules: delete one to add another.`}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={full} onClick={() => setEditing(NEW_LLM)}>
              <Plus />
              LLM rule
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={full}
              onClick={() => setEditing(NEW_PHRASE)}
            >
              <Plus />
              Phrase rule
            </Button>
          </div>
        </>
      }
      notice={
        results.isError && (
          <p className="px-5 pt-4 text-p-400 text-destructive">
            Could not load the results: {results.error.message}
          </p>
        )
      }
    >
      {agent.rules.length === 0 ? (
        <p className="px-5 py-8 text-center text-p-400 text-muted-foreground">
          No rules yet. Add an LLM rule for what the judge model should check, or a phrase rule for
          words the agent must or must not say.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)_6rem_3rem] gap-x-3 border-b px-5 py-2 text-label text-secondary">
            <span>Rule</span>
            <span className="col-span-2">
              <Explained hint={RESULTS_NOTE}>Results</Explained>
            </span>
          </div>
          <ul className="divide-y">
            {agent.rules.map((rule) => (
              <RuleRow
                key={rule.key}
                rule={rule}
                results={results}
                onEdit={() => setEditing(rule)}
              />
            ))}
          </ul>
        </>
      )}
      {editing && (
        <RuleDialog
          key={editing.key || editing.kind}
          agentId={agent.id}
          rule={editing}
          onClosed={() => setEditing(null)}
        />
      )}
    </ActionPanel>
  );
}

type ResultsQuery = ReturnType<typeof useRuleResults>;

function RuleRow({
  rule,
  results,
  onEdit,
}: {
  rule: AgentRule;
  results: ResultsQuery;
  onEdit: () => void;
}) {
  const result = results.data?.find((found) => found.key === rule.key);
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_6rem_3rem] items-center gap-x-3 gap-y-1.5 px-5 py-3 transition-colors duration-150 hover:bg-hv1 has-[>button:active]:bg-muted">
      <button
        type="button"
        onClick={onEdit}
        className="grid min-w-0 gap-0.5 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        <span className="truncate text-s-500" title={rule.name}>
          {rule.name}
        </span>
        <span className="truncate text-xs-400 text-muted-foreground">
          {summary(rule)} · {ROLE_TEXT[rule.role]}
        </span>
      </button>
      <Results query={results} result={result} name={rule.name} />
      {result && result.failures.length > 0 && (
        <p className="col-span-full text-xs-400 text-muted-foreground">
          Latest fails:{" "}
          {result.failures.map((failure, index) => (
            <Fragment key={failure.conversation_id}>
              {index > 0 && ", "}
              <Link
                to={`/conversations/${failure.conversation_id}`}
                className="rounded-sm text-foreground underline decoration-muted-foreground/40 underline-offset-[3px] outline-none hover:decoration-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                {failure.scenario_name}
              </Link>
              {failure.ended_at && ` ${when(failure.ended_at)}`}
            </Fragment>
          ))}
        </p>
      )}
    </li>
  );
}

/** A rule's results, across the two result columns of its row. */
function Results({
  query,
  result,
  name,
}: {
  query: ResultsQuery;
  result: RuleResults | undefined;
  name: string;
}) {
  if (query.isPending) return <Skeleton className="col-span-2 h-4" />;
  if (query.isError) return <span className="col-span-2" />;
  if (!result || Object.keys(result.counts).length === 0) {
    return (
      <span className="col-span-2 text-right text-xs-400 text-muted-foreground">
        No judged calls yet
      </span>
    );
  }
  return <OutcomeCounts counts={result.counts} label={name} />;
}

/** Adds or edits one rule. A save applies to the rules as they are when it starts. */
function RuleDialog({
  agentId,
  rule,
  onClosed,
}: {
  agentId: string;
  rule: AgentRule;
  onClosed: () => void;
}) {
  const save = useSaveRules(agentId);
  const [draft, setDraft] = useState(rule);
  const [submitted, setSubmitted] = useState(false);
  const guard = useCloseGuard(JSON.stringify(draft) !== JSON.stringify(rule));
  const adding = !rule.key;

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const valid = Object.keys(ruleProblems(draft)).length === 0;
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    save.mutate(
      (current) => {
        if (adding) return [...current, draft];
        if (!current.some((saved) => saved.key === rule.key)) {
          throw new Error("This rule was deleted meanwhile. Reload the page.");
        }
        return current.map((saved) => (saved.key === rule.key ? draft : saved));
      },
      {
        onSuccess: () => {
          guard.close();
          toast.success(adding ? "Rule added" : "Rule saved");
        },
      },
    );
  };

  return (
    <Dialog
      open={guard.open}
      onOpenChange={(next) => !next && guard.requestClose()}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-xl">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>{adding ? `Add ${KIND[rule.kind].label}` : `Edit ${rule.name}`}</DialogTitle>
          <DialogDescription>
            {KIND[rule.kind].note}
            {!adding && ` ${KIND[rule.kind].edit}`}
          </DialogDescription>
        </DialogHeader>

        <form
          id="rule-form"
          noValidate
          onSubmit={submit}
          className="min-h-0 flex-1 overflow-y-auto px-6 pt-1 pb-6"
        >
          <RuleFields
            rule={draft}
            submitted={submitted}
            onChange={(next) => {
              save.reset();
              setDraft(next);
            }}
          />
        </form>

        {save.error && <FieldError className="px-6 pb-3">{save.error.message}</FieldError>}

        <DialogFooter className="border-t px-6 py-4">
          {!adding && (
            <DeleteConfirm
              name={rule.name}
              description="Calls already judged keep their results for it."
              pending={save.isPending}
              onDelete={(close) =>
                save.mutate((current) => current.filter((saved) => saved.key !== rule.key), {
                  onSuccess: () => {
                    guard.close();
                    toast.success(`Deleted ${rule.name}`);
                  },
                  onSettled: close,
                })
              }
            />
          )}
          <Button type="button" variant="ghost" onClick={guard.requestClose}>
            Cancel
          </Button>
          <Button type="submit" form="rule-form" disabled={save.isPending}>
            {save.isPending && <Spinner />}
            {adding ? "Add rule" : "Save changes"}
          </Button>
        </DialogFooter>

        <DiscardConfirm subject="rule" {...guard.discard} />
      </DialogContent>
    </Dialog>
  );
}
