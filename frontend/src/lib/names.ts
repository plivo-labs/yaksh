/** The longest name of a scenario or a persona, as the API takes it. */
export const MAX_NAME_CHARS = 80;

/** The name, or the name with " (2)", " (3)"… when `taken` holds it, within the limit: the
 * same rule the API uses for forks. `taken` holds names as `key` compares them: lower case
 * unless told otherwise. */
export function freeName(
  name: string,
  taken: ReadonlySet<string>,
  limit: number = MAX_NAME_CHARS,
  key: (name: string) => string = (text) => text.toLowerCase(),
): string {
  let candidate = name.slice(0, limit);
  for (let n = 2; taken.has(key(candidate)); n++) {
    const suffix = ` (${n})`;
    candidate = `${name.slice(0, limit - suffix.length)}${suffix}`;
  }
  return candidate;
}

/** Saves drafted forks one by one, each under a name free against the names in use right
 * before the save, and reports each saved id. */
export function forkSaver<T extends { name: string }>(
  takenNames: () => Promise<string[]>,
  saveOne: (draft: T) => Promise<{ id: string }>,
) {
  return async (
    chosen: { draft: T; index: number }[],
    done: (index: number, id: string) => void,
  ) => {
    const taken = new Set((await takenNames()).map((name) => name.toLowerCase()));
    for (const { draft, index } of chosen) {
      const name = freeName(draft.name, taken);
      taken.add(name.toLowerCase());
      done(index, (await saveOne({ ...draft, name })).id);
    }
  };
}
