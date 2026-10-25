import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useModelEfforts } from "@/lib/queries";

const UNSET = "unset";

/** The reasoning efforts the model takes, as Yaksh checked them with the provider. `unset`
 * names what no effort means for this field. */
export function EffortSelect({
  id,
  model,
  value,
  onValueChange,
  unset,
}: {
  id: string;
  model: string;
  value: string | null;
  onValueChange: (effort: string | null) => void;
  unset: string;
}) {
  const efforts = useModelEfforts(model);
  if (efforts.isPending) {
    return (
      <span className="flex items-center gap-2 text-s-400 text-muted-foreground">
        <Spinner /> Checking which efforts {model} takes
      </span>
    );
  }
  if (efforts.isError) {
    return (
      <span className="text-s-400">
        {value ?? unset}
        <span className="block text-xs-400 text-muted-foreground">
          Can't check this model: {efforts.error.message}
        </span>
      </span>
    );
  }
  const taken = efforts.data.efforts;
  if (taken.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Badge>This model has no reasoning</Badge>
        {value !== null && (
          <Button size="sm" variant="outline" onClick={() => onValueChange(null)}>
            Send no effort
          </Button>
        )}
      </div>
    );
  }
  const items = [
    { value: UNSET, label: unset },
    ...taken.map((effort) => ({ value: effort, label: effort })),
  ];
  const refused = value !== null && !taken.includes(value);
  return (
    <>
      <Select
        items={items}
        value={value ?? UNSET}
        onValueChange={(next) => next && onValueChange(next === UNSET ? null : next)}
      >
        <SelectTrigger id={id} className="w-56" aria-invalid={refused}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {refused && (
        <span className="text-xs-400 text-destructive">
          {model} does not take {value}; choose another effort.
        </span>
      )}
    </>
  );
}
