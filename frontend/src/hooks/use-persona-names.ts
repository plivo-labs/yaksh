import { usePersonas } from "@/lib/queries";

/** The personas, and a persona's name by id that says when the names are loading or could not
 * load, so a list never shows a blank or a raw id. */
export function usePersonaNames() {
  const personas = usePersonas();
  const names = new Map((personas.data ?? []).map((persona) => [persona.id, persona.name]));
  const name = (id: string) =>
    names.get(id) ??
    (personas.isPending ? "Loading" : personas.isError ? "Persona not loaded" : "Unknown persona");
  return { personas, name };
}
