/** Mix personas into a run: each scenario keeps its own persona and gets `perScenario - 1`
 * more, dealt from a shuffled deck of the pool. A persona is never twice on one scenario, and
 * each persona of the pool is dealt once before any is dealt again. */
export function mixPersonas(
  scenarios: { id: string; persona_id: string }[],
  pool: string[],
  perScenario: number,
  random: () => number = Math.random,
): Record<string, string[]> {
  let deck: string[] = [];
  const draw = (taken: Set<string>): string | undefined => {
    if (pool.every((id) => taken.has(id))) return undefined;
    // Cards this scenario cannot take stay at the front for the next scenario.
    if (!deck.some((id) => !taken.has(id))) deck = [...deck, ...shuffled(pool, random)];
    const index = deck.findIndex((id) => !taken.has(id));
    return deck.splice(index, 1)[0];
  };
  const mixed: Record<string, string[]> = {};
  for (const scenario of scenarios) {
    const picked = [scenario.persona_id];
    const taken = new Set(picked);
    while (picked.length < perScenario) {
      const next = draw(taken);
      if (next === undefined) break;
      picked.push(next);
      taken.add(next);
    }
    mixed[scenario.id] = picked;
  }
  return mixed;
}

function shuffled(items: string[], random: () => number): string[] {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index--) {
    const other = Math.floor(random() * (index + 1));
    [copy[index], copy[other]] = [copy[other], copy[index]];
  }
  return copy;
}
