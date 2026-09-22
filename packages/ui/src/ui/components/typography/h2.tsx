import type { HTMLAttributes } from "react";
import { cn } from "../../../lib/cn";

export interface H2Props extends HTMLAttributes<HTMLHeadingElement> {
  variant?: "sm" | "md" | "lg";
}

export function H2({ variant = "md", className, ...rest }: H2Props) {
  return <h2 className={cn("rui-h2", className)} data-variant={variant} {...rest} />;
}
