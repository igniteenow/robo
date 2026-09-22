import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type DivProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className, ...rest }: DivProps) {
  return <div className={cn("rui-card", className)} {...rest} />;
}

export function CardHeader({ className, ...rest }: DivProps) {
  return <div className={cn("rui-card__header", className)} {...rest} />;
}

export function CardTitle({ className, ...rest }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("rui-card__title", className)} {...rest} />;
}

export function CardDescription({ className, ...rest }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("rui-card__desc", className)} {...rest} />;
}

export function CardContent({ className, ...rest }: DivProps) {
  return <div className={cn("rui-card__content", className)} {...rest} />;
}

export function CardFooter({ className, ...rest }: DivProps) {
  return <div className={cn("rui-card__content", className)} {...rest} />;
}
