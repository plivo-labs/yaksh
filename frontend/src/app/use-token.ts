import { useEffect, useState } from "react";

import { type Credential, getToken, setToken } from "@/lib/api";

/** The stored token, cleared when the server refuses it and followed across tabs. */
export function useToken(credential: Credential): [string, (token: string) => void] {
  const [token, setState] = useState(() => getToken(credential));
  useEffect(() => {
    const clear = () => {
      setToken(credential, "");
      setState("");
    };
    const follow = (event: StorageEvent) => {
      if (event.key === credential.key) setState(event.newValue ?? "");
    };
    window.addEventListener(credential.refused, clear);
    window.addEventListener("storage", follow);
    return () => {
      window.removeEventListener(credential.refused, clear);
      window.removeEventListener("storage", follow);
    };
  }, [credential]);
  return [
    token,
    (next: string) => {
      setToken(credential, next);
      setState(next);
    },
  ];
}
