import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { listen } from "@/lib/listen";

/** Plays a live call: the agent on the left, the caller on the right. The audio stops when
 * the call ends, on a second click, or when the button leaves the page. */
export function LiveListen({ conversationId }: { conversationId: string }) {
  const running = useRef<AbortController | null>(null);
  const [listening, setListening] = useState(false);

  useEffect(() => () => running.current?.abort(), []);

  const toggle = () => {
    if (running.current) {
      running.current.abort();
      return;
    }
    const controller = new AbortController();
    running.current = controller;
    setListening(true);
    listen(conversationId, controller.signal)
      .catch((error: Error) => {
        if (!controller.signal.aborted) {
          toast.error("Could not play the call", { description: error.message });
        }
      })
      .finally(() => {
        if (running.current === controller) running.current = null;
        setListening(false);
      });
  };

  return (
    <Button variant="outline" size="sm" onClick={toggle}>
      {listening ? "Stop listening" : "Listen"}
    </Button>
  );
}
