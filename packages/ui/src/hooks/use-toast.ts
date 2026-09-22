import { useCallback, useEffect, useRef, useState } from "react";

export type ToastType = "success" | "error" | "info" | "warning";

export interface ToastState {
  message: string;
  type: ToastType;
  /** Changes on every call so identical consecutive messages re-announce. */
  id: number;
}

export interface UseToastResult {
  toast: ToastState | null;
  showToast: (message: string, type?: ToastType, durationMs?: number) => void;
  dismissToast: () => void;
}

const DEFAULT_DURATION_MS = 3500;

/** One transient message at a time. Render it with `<Toast toast={toast} />`. */
export function useToast(): UseToastResult {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const counter = useRef(0);

  const clear = useCallback((): void => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const dismissToast = useCallback((): void => {
    clear();
    setToast(null);
  }, [clear]);

  const showToast = useCallback(
    (message: string, type: ToastType = "info", durationMs: number = DEFAULT_DURATION_MS): void => {
      clear();
      counter.current += 1;
      setToast({ message, type, id: counter.current });
      if (durationMs > 0) timer.current = setTimeout(() => setToast(null), durationMs);
    },
    [clear],
  );

  useEffect(() => clear, [clear]);

  return { toast, showToast, dismissToast };
}
