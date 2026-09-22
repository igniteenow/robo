import { useEffect, useState } from "react";

/** True while the viewport is narrower than `px`. Safe during server render
 *  (returns false) and updates live as the window is resized. */
export function useBelowBreakpoint(px: number): boolean {
  const query = `(max-width: ${Math.max(0, px - 1)}px)`;
  const read = (): boolean =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false;

  const [below, setBelow] = useState<boolean>(read);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    const onChange = (): void => setBelow(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return below;
}
