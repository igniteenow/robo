import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

export type ButtonSize = "xs" | "sm" | "md" | "icon";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "prefix"> {
  size?: ButtonSize;
  /** Bordered, transparent background. */
  outlined?: boolean;
  /** No border or background until hovered. */
  ghost?: boolean;
  /** Dangerous action. Combines with `outlined` / `ghost`. */
  destructive?: boolean;
  /** Icon or spinner shown before the label. */
  prefix?: ReactNode;
  /** Icon shown after the label. */
  suffix?: ReactNode;
}

/** Defaults to `type="button"` so a Button never submits a form by accident;
 *  pass `type="submit"` where that is the intent. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { size = "md", outlined, ghost, destructive, prefix, suffix, className, type, children, ...rest },
  ref,
) {
  const variant = ghost ? "ghost" : outlined ? "outlined" : "solid";
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={cn("rui-btn", className)}
      data-size={size}
      data-variant={variant}
      data-destructive={destructive ? "true" : undefined}
      {...rest}
    >
      {prefix}
      {children}
      {suffix}
    </button>
  );
});
