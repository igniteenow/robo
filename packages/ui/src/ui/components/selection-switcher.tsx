import { useEffect } from "react";

/** Mount once at the app root. Records on <html> whether the person is driving
 *  with the keyboard or a pointer (`data-input="keyboard" | "pointer"`), so
 *  styles can show stronger focus and selection cues for keyboard use. Renders
 *  nothing. */
export function SelectionSwitcher(): null {
  useEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    const set = (mode: "keyboard" | "pointer") => (): void => {
      if (root.dataset.input !== mode) root.dataset.input = mode;
    };
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Tab" || event.key.startsWith("Arrow")) set("keyboard")();
    };
    const onPointer = set("pointer");
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer, true);
      delete root.dataset.input;
    };
  }, []);
  return null;
}
