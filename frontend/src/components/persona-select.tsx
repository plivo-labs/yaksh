import { FieldError } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePersonas } from "@/lib/queries";

/** A persona picker that says when the personas are loading, could not load, or do not exist
 * yet. Place it inside a Field. */
export function PersonaSelect({
  id,
  value,
  onValueChange,
  invalid = false,
}: {
  id: string;
  value: string;
  onValueChange: (id: string) => void;
  invalid?: boolean;
}) {
  const personas = usePersonas();
  const items = (personas.data ?? []).map((persona) => ({
    value: persona.id,
    label: persona.name,
  }));
  const listed = items.some((item) => item.value === value);
  return (
    <>
      <Select
        items={items}
        value={listed ? value : null}
        onValueChange={(next) => next && onValueChange(next)}
        disabled={items.length === 0}
      >
        <SelectTrigger id={id} className="w-full" aria-invalid={invalid}>
          <SelectValue
            placeholder={
              personas.isPending
                ? "Loading personas"
                : personas.isError
                  ? "Could not load the personas"
                  : items.length === 0
                    ? "No personas yet"
                    : value
                      ? "A persona not in the list"
                      : "Choose a persona"
            }
          />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {personas.isError && <FieldError>{personas.error.message}</FieldError>}
    </>
  );
}
