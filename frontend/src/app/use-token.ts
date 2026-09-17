import { useEffect, useState } from "react";

import { UNAUTHORIZED_EVENT, getToken, setToken } from "@/lib/api";

export function useToken(): [string, (token: string) => void] {
  const [token, setState] = useState(getToken);
  useEffect(() => {
    const clear = () => {
      setToken("");
      setState("");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, clear);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, clear);
  }, []);
  return [
    token,
    (next: string) => {
      setToken(next);
      setState(next);
    },
  ];
}
