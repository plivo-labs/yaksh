/** The longest name of a scenario or a persona, as the API takes it. */
export const MAX_NAME_CHARS = 80;

/** The name, or the name with " (2)", " (3)"… when `taken` (lower case) holds it, within the
 * name limit: the same rule the API uses for forks. */
export function freeName(name: string, taken: ReadonlySet<string>): string {
  let candidate = name;
  for (let n = 2; taken.has(candidate.toLowerCase()); n++) {
    const suffix = ` (${n})`;
    candidate = `${name.slice(0, MAX_NAME_CHARS - suffix.length)}${suffix}`;
  }
  return candidate;
}
