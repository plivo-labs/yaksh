import { useSearchParams } from "react-router";

/** The URL params and a function that changes some of them in place. A key set to null or ""
 * goes away. Each change goes back to the first page. */
export function useFilterParams() {
  const [params, setParams] = useSearchParams();
  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    next.delete("page");
    setParams(next, { replace: true });
  };
  return [params, update] as const;
}
