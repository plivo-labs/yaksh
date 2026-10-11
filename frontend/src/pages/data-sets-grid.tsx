import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FieldDescription, FieldError, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { nextDataSetName } from "@/lib/data-sets";
import type { DataSet } from "@/lib/types";

type Kind = "known_facts" | "agent_data";

const MAX_ROWS = 30;

/** The scenario's data sets: one row for each name, one column for each data set. A scenario
 * with one data set shows its values without a name. */
export function DataSetsGrid({
  dataSets,
  outbound,
  limit,
  submitted,
  problem,
  onChange,
}: {
  dataSets: DataSet[];
  outbound: boolean;
  /** The most data sets a scenario holds, from Settings. */
  limit: number;
  submitted: boolean;
  problem: string | null;
  onChange: (dataSets: DataSet[]) => void;
}) {
  const many = dataSets.length > 1;
  const columns = `minmax(8rem,11rem) repeat(${dataSets.length}, minmax(${many ? "9rem" : "0"},1fr)) 2.25rem`;

  const setName = (kind: Kind, row: number, name: string) =>
    onChange(
      dataSets.map((dataSet) => ({
        ...dataSet,
        [kind]: dataSet[kind].map((fact, at) => (at === row ? { ...fact, name } : fact)),
      })),
    );
  const setValue = (index: number, kind: Kind, row: number, value: string) =>
    onChange(
      dataSets.map((dataSet, at) =>
        at === index
          ? {
              ...dataSet,
              [kind]: dataSet[kind].map((fact, r) => (r === row ? { ...fact, value } : fact)),
            }
          : dataSet,
      ),
    );
  const addRow = (kind: Kind) =>
    onChange(
      dataSets.map((dataSet) => ({
        ...dataSet,
        [kind]: [...dataSet[kind], { name: "", value: "" }],
      })),
    );
  const removeRow = (kind: Kind, row: number) =>
    onChange(
      dataSets.map((dataSet) => ({
        ...dataSet,
        [kind]: dataSet[kind].filter((_, at) => at !== row),
      })),
    );
  const addDataSet = () => {
    const last = dataSets[dataSets.length - 1];
    onChange([
      ...dataSets,
      {
        name: nextDataSetName(dataSets),
        known_facts: last.known_facts,
        agent_data: last.agent_data,
      },
    ]);
  };
  const rename = (index: number, name: string) =>
    onChange(dataSets.map((dataSet, at) => (at === index ? { ...dataSet, name } : dataSet)));
  const removeDataSet = (index: number) => onChange(dataSets.filter((_, at) => at !== index));

  const rows = (kind: Kind, label: string, mono: boolean) =>
    dataSets[0][kind].map((fact, row) => (
      <div key={`${kind}-${row}`} className="contents">
        <Input
          aria-label={`${label} ${row + 1} name`}
          aria-invalid={submitted && !fact.name.trim()}
          placeholder="Name"
          maxLength={80}
          className={mono ? "font-mono text-s-400" : undefined}
          value={fact.name}
          onChange={(e) => setName(kind, row, e.target.value)}
        />
        {dataSets.map((dataSet, index) => (
          <Input
            key={index}
            aria-label={`${fact.name || `${label} ${row + 1}`}, ${many ? dataSet.name : "value"}`}
            aria-invalid={submitted && !dataSet[kind][row].value.trim()}
            placeholder="Value"
            maxLength={500}
            value={dataSet[kind][row].value}
            onChange={(e) => setValue(index, kind, row, e.target.value)}
          />
        ))}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={`Remove ${fact.name || `${label.toLowerCase()} ${row + 1}`}`}
          onClick={() => removeRow(kind, row)}
        >
          <X />
        </Button>
      </div>
    ));

  const addRowButton = (kind: Kind, label: string) => (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="col-span-full justify-self-start"
      disabled={dataSets[0][kind].length >= MAX_ROWS}
      onClick={() => addRow(kind)}
    >
      <Plus />
      {label}
    </Button>
  );

  return (
    <FieldSet className="min-w-0">
      <div className="flex items-baseline justify-between gap-3">
        <FieldLegend variant="label">{many ? "Data sets" : "What the caller knows"}</FieldLegend>
        <Button
          type="button"
          variant="link"
          size="sm"
          disabled={dataSets.length >= limit}
          title={
            dataSets.length >= limit ? `A scenario holds at most ${limit} data sets.` : undefined
          }
          onClick={addDataSet}
        >
          <Plus />
          Add data set
        </Button>
      </div>
      <FieldDescription>
        {many
          ? "Each column is one data set: the same names with other values. A run plays every data set. Write dates relative to today, for example next Thursday."
          : "Write dates relative to today, for example next Thursday. Add a data set to play this scenario again with other values."}
      </FieldDescription>
      {/* One scroll area for every row, so each column stays under its data set's name. */}
      <div className="overflow-x-auto">
        <div className="grid min-w-0 items-center gap-2" style={{ gridTemplateColumns: columns }}>
          {many && (
            <>
              <span className="text-xs-400 text-muted-foreground">Name</span>
              {dataSets.map((dataSet, index) => (
                <div key={index} className="flex min-w-0 items-center gap-1">
                  <Input
                    aria-label={`Data set ${index + 1} name`}
                    aria-invalid={submitted && !dataSet.name.trim()}
                    maxLength={40}
                    className="min-w-0 bg-muted/40 text-s-500"
                    value={dataSet.name}
                    onChange={(e) => rename(index, e.target.value)}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove the data set ${dataSet.name}`}
                    onClick={() => removeDataSet(index)}
                  >
                    <X />
                  </Button>
                </div>
              ))}
              <span />
              <span className="col-span-full pt-2 text-xs-500 text-muted-foreground">
                What the caller knows
              </span>
            </>
          )}
          {rows("known_facts", "Fact", false)}
          {addRowButton("known_facts", "Add fact")}
          {outbound && (
            <>
              <span className="col-span-full pt-3 text-xs-500 text-muted-foreground">
                Data sent to the agent
              </span>
              <FieldDescription className="col-span-full">
                Yaksha puts these in the request that starts the call, as{" "}
                <code>{"{{agent_data.<name>}}"}</code>. The caller does not see them; the judge
                does.
              </FieldDescription>
              {rows("agent_data", "Agent data", true)}
              {addRowButton("agent_data", "Add item")}
            </>
          )}
        </div>
      </div>
      {submitted && problem && <FieldError>{problem}</FieldError>}
    </FieldSet>
  );
}
