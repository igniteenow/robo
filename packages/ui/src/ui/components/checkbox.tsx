import { forwardRef } from "react";
import type { ChangeEvent, InputHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "checked" | "onChange"> {
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

/** A real `<input type="checkbox">`, so labels, forms and the keyboard all work
 *  natively. */
export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { checked, onCheckedChange, className, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      type="checkbox"
      className={cn("rui-check", className)}
      checked={checked ?? false}
      onChange={(event: ChangeEvent<HTMLInputElement>) => onCheckedChange?.(event.target.checked)}
      {...rest}
    />
  );
});
