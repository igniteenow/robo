import type { HTMLAttributes } from "react";
import { cn } from "../../../lib/cn";

export { H2 } from "./h2";
export type { H2Props } from "./h2";

export type TypographyProps = HTMLAttributes<HTMLDivElement>;

/** Brand display face for wordmarks and short headings. Size, weight, tracking
 *  and case come from `className`. */
export function Typography({ className, ...rest }: TypographyProps) {
  return <div className={cn("rui-type", className)} {...rest} />;
}
