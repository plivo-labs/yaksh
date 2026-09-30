import { useSearchParams } from "react-router";

/** The page in the URL, from 1. */
export function usePageParam(): number {
  const [params] = useSearchParams();
  return Math.max(1, Number(params.get("page") ?? "1") || 1);
}
