import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export type BadgeTone = "default" | "secondary" | "outline" | "success" | "warning" | "destructive";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

export function Badge({ tone = "default", className, ...rest }: BadgeProps) {
  return <span className={cn("rui-badge", className)} data-tone={tone} {...rest} />;
}
