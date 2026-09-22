import { forwardRef } from "react";
import type { ChangeEvent, OptionHTMLAttributes, SelectHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export interface SelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange" | "multiple"> {
  value?: string;
  onValueChange?: (value: string) => void;
  /** Shown, unselectable, while `value` is empty. */
  placeholder?: string;
}

/** Native `<select>`: the platform picker on touch devices, full keyboard and
 *  screen-reader support everywhere, nothing to position or trap. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { value, onValueChange, placeholder, className, children, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      className={cn("rui-select", className)}
      value={value ?? ""}
      onChange={(event: ChangeEvent<HTMLSelectElement>) => onValueChange?.(event.target.value)}
      {...rest}
    >
      {placeholder !== undefined && (
        <option value="" disabled hidden>
          {placeholder}
        </option>
      )}
      {children}
    </select>
  );
});

export type SelectOptionProps = OptionHTMLAttributes<HTMLOptionElement>;

export function SelectOption(props: SelectOptionProps) {
  return <option {...props} />;
}
