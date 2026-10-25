import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { listen, type LiveView } from "@/lib/listen";

export interface LiveListen {
  listening: boolean;
  /** What has played so far, once the first sound plays. */
  view: LiveView | null;
  toggle: () => void;
}

/** Listening to a live call: the agent on the left, the caller on the right. The audio stops
 * when the call ends, on a second toggle, or when the component that holds it unmounts. */
export function useLiveListen(conversationId: string): LiveListen {
  const running = useRef<AbortController | null>(null);
  const [listening, setListening] = useState(false);
  const [view, setView] = useState<LiveView | null>(null);

  useEffect(() => () => running.current?.abort(), []);

  const toggle = () => {
    if (running.current) {
      running.current.abort();
      return;
    }
    const controller = new AbortController();
    running.current = controller;
    setListening(true);
    listen(conversationId, controller.signal, setView)
      .catch((error: Error) => {
        if (!controller.signal.aborted) {
          toast.error("Could not play the call", { description: error.message });
        }
      })
      .finally(() => {
        if (running.current === controller) running.current = null;
        setListening(false);
        setView(null);
      });
  };

  return { listening, view, toggle };
}
