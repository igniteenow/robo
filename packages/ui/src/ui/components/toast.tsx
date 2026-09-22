import type { ToastType } from "../../hooks/use-toast";
import { cn } from "../../lib/cn";
import { Portal } from "../../lib/overlay";

/** What a toast needs to be shown. `useToast()` produces this (with an `id`),
 *  and so does any state a screen keeps for itself as `{ message, type }`. */
export interface ToastLike {
  message: string;
  type: ToastType;
  id?: number;
}

export interface ToastProps {
  /** Renders nothing while null. */
  toast: ToastLike | null;
  className?: string;
}

export function Toast({ toast, className }: ToastProps) {
  if (!toast) return null;
  const urgent = toast.type === "error";
  return (
    <Portal>
      <div
        key={toast.id ?? toast.message}
        role={urgent ? "alert" : "status"}
        aria-live={urgent ? "assertive" : "polite"}
        data-type={toast.type}
        className={cn("rui-toast", className)}
      >
        {toast.message}
      </div>
    </Portal>
  );
}
