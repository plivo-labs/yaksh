import { useEffect, useState } from "react";

/** The time now, again every `every` ms, for times that age while the page is open. */
export function useNow(every: number): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), every);
    return () => clearInterval(tick);
  }, [every]);
  return now;
}
