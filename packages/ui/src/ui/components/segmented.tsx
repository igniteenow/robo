import { useRef } from "react";
import type { HTMLAttributes, KeyboardEvent, ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface SegmentedOption<T extends string = string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
}

export interface SegmentedProps<T extends string = string>
  extends Omit<HTMLAttributes<HTMLDivElement>, "onChange"> {
  value: T;
  onChange: (value: T) => void;
  options: ReadonlyArray<SegmentedOption<T>>;
  size?: "sm" | "md";
}

/** Pick exactly one of a few options. A radio group: arrow keys move and select,
 *  Tab enters and leaves as a single stop. */
export function Segmented<T extends string = string>({
  value,
  onChange,
  options,
  size = "sm",
  className,
  ...rest
}: SegmentedProps<T>) {
  const group = useRef<HTMLDivElement>(null);

  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number): void => {
    const step =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    if (step === 0) return;
    event.preventDefault();
    const count = options.length;
    for (let i = 1; i <= count; i += 1) {
      const next = (index + step * i + count * i) % count;
      if (!options[next].disabled) {
        onChange(options[next].value);
        group.current?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
        return;
      }
    }
  };

  return (
    <div ref={group} role="radiogroup" data-size={size} className={cn("rui-seg", className)} {...rest}>
      {options.map((option, index) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked || (index === 0 && !options.some((o) => o.value === value)) ? 0 : -1}
            disabled={option.disabled}
            className="rui-seg__opt"
            onClick={() => onChange(option.value)}
            onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => move(event, index)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export interface FilterGroupProps extends HTMLAttributes<HTMLDivElement> {
  label: ReactNode;
}

/** A labelled slot for one filter control. */
export function FilterGroup({ label, className, children, ...rest }: FilterGroupProps) {
  return (
    <div role="group" className={cn("rui-filter", className)} {...rest}>
      <span className="rui-filter__label">{label}</span>
      {children}
    </div>
  );
}
