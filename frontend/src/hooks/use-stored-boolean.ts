import { useState } from "react";

import { storage } from "@/lib/storage";

/** An on or off choice that carries over in this browser. */
export function useStoredBoolean(
  key: string,
  fallback: boolean,
): [boolean, (next: boolean) => void] {
  const [value, setValue] = useState(() => {
    const saved = storage.getItem(key);
    return saved === null ? fallback : saved === "true";
  });
  const save = (next: boolean) => {
    setValue(next);
    storage.setItem(key, String(next));
  };
  return [value, save];
}
