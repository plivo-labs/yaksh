import { useLayoutEffect, useState } from "react";
import { flushSync } from "react-dom";

const THEME_KEY = "yaksh.theme";

export function useDarkMode(): [boolean, () => void] {
  const [dark, setDark] = useState(() => {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      if (saved) return saved === "dark";
    } catch {
      // storage unavailable
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
    } catch {
      // storage unavailable
    }
  }, [dark]);
  const toggle = () => {
    const flip = () => flushSync(() => setDark((value) => !value));
    if (document.startViewTransition) document.startViewTransition(flip);
    else flip();
  };
  return [dark, toggle];
}
