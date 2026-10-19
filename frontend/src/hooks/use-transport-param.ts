import { useFilterParams } from "@/hooks/use-filter-params";
import type { Transport } from "@/lib/types";

/** The transport in the address's `transport` parameter, and a function that sets it. */
export function useTransportParam() {
  const [params, update] = useFilterParams();
  const value = params.get("transport");
  const transport: Transport | undefined =
    value === "phone" || value === "text" ? value : undefined;
  const setTransport = (next: Transport | undefined) => update({ transport: next ?? null });
  return [transport, setTransport] as const;
}
