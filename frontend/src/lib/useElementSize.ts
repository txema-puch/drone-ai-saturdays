import { useEffect, useRef, useState } from "react";

/** Track an element's content height via ResizeObserver — used to give
 *  react-window's fixed-size list an explicit pixel height without pulling in
 *  react-virtualized-auto-sizer. */
export function useElementHeight<T extends HTMLElement>(fallback = 600) {
  const ref = useRef<T>(null);
  const [height, setHeight] = useState(fallback);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const h = entry.contentRect.height;
        if (h > 0) setHeight(h);
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, height };
}
