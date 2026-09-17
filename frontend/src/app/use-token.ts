import { useEffect, useState } from "react";

import { TOKEN_KEY, UNAUTHORIZED_EVENT, getToken, setToken } from "@/lib/api";

export function useToken(): [string, (token: string) => void] {
  const [token, setState] = useState(getToken);
  useEffect(() => {
    const clear = () => {
      setToken("");
      setState("");
    };
    const follow = (event: StorageEvent) => {
      if (event.key === TOKEN_KEY) setState(event.newValue ?? "");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, clear);
    window.addEventListener("storage", follow);
    return () => {
      window.removeEventListener(UNAUTHORIZED_EVENT, clear);
      window.removeEventListener("storage", follow);
    };
  }, []);
  return [
    token,
    (next: string) => {
      setToken(next);
      setState(next);
    },
  ];
}
