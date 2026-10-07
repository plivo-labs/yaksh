import { type DragEvent, useEffect, useRef, useState } from "react";

function carriesFiles(event: DragEvent): boolean {
  return event.dataTransfer.types.includes("Files");
}

/** Files dropped on one element. `target` goes on that element; `dragging` is true while files
 * are over it. A `refusal` refuses the drop. A file dropped anywhere else on the page is refused,
 * so the browser does not open it in place of the page. */
export function useFileDrop(onFiles: (files: File[]) => void, refusal: string | null = null) {
  const depth = useRef(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const refuse = (event: globalThis.DragEvent) => {
      if (event.defaultPrevented || !event.dataTransfer?.types.includes("Files")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "none";
    };
    window.addEventListener("dragover", refuse);
    window.addEventListener("drop", refuse);
    return () => {
      window.removeEventListener("dragover", refuse);
      window.removeEventListener("drop", refuse);
    };
  }, []);

  const target = {
    onDragEnter: (event: DragEvent<HTMLElement>) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    onDragOver: (event: DragEvent<HTMLElement>) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = refusal ? "none" : "copy";
    },
    onDragLeave: (event: DragEvent<HTMLElement>) => {
      if (!carriesFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    onDrop: (event: DragEvent<HTMLElement>) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      if (!refusal) onFiles(Array.from(event.dataTransfer.files));
    },
  };
  return { dragging, target };
}
