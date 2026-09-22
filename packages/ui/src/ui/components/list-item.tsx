import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export interface ListItemProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Highlighted: the current selection or keyboard cursor. */
  active?: boolean;
}

export const ListItem = forwardRef<HTMLButtonElement, ListItemProps>(function ListItem(
  { active = false, className, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={cn("rui-item", className)}
      data-active={active ? "true" : undefined}
      {...rest}
    />
  );
});
