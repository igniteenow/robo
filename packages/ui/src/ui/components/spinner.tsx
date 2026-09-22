import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export interface SpinnerProps extends HTMLAttributes<HTMLSpanElement> {
  /** Announced to screen readers. Pass "" when a nearby label already says it. */
  label?: string;
}

/** Sized by font-size: `className="text-2xl"` makes a bigger spinner. */
export function Spinner({ label = "Loading", className, ...rest }: SpinnerProps) {
  return (
    <span
      role={label ? "status" : undefined}
      aria-label={label || undefined}
      aria-hidden={label ? undefined : true}
      className={cn("rui-spinner", className)}
      {...rest}
    />
  );
}
