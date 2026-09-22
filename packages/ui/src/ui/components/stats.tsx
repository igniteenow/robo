import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface StatItem {
  label: ReactNode;
  value: ReactNode;
  /** Optional smaller line under the value. */
  hint?: ReactNode;
}

export interface StatsProps extends HTMLAttributes<HTMLDListElement> {
  items: StatItem[];
}

export function Stats({ items, className, ...rest }: StatsProps) {
  return (
    <dl className={cn("rui-stats", className)} {...rest}>
      {items.map((item, index) => (
        <div className="rui-stats__cell" key={index}>
          <dt className="rui-stats__label">{item.label}</dt>
          <dd className="rui-stats__value" style={{ margin: 0 }}>
            {item.value}
          </dd>
          {item.hint !== undefined && <dd className="rui-card__desc" style={{ margin: 0 }}>{item.hint}</dd>}
        </div>
      ))}
    </dl>
  );
}
