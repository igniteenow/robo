import { useEffect, useRef, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";
import { Button } from "./button";

async function writeClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through: blocked, or not a secure context */
  }
  if (typeof document === "undefined") return false;
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(area);
  return ok;
}

export interface CopyButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "prefix"> {
  text: string;
  label?: ReactNode;
  copiedLabel?: ReactNode;
}

export function CopyButton({
  text,
  label = "Copy",
  copiedLabel = "Copied",
  onClick,
  ...rest
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );
  return (
    <Button
      size="xs"
      ghost
      aria-live="polite"
      onClick={(event) => {
        onClick?.(event);
        void writeClipboard(text).then((ok) => {
          if (!ok) return;
          setCopied(true);
          if (timer.current !== null) clearTimeout(timer.current);
          timer.current = setTimeout(() => setCopied(false), 1600);
        });
      }}
      {...rest}
    >
      {copied ? copiedLabel : label}
    </Button>
  );
}

export interface CommandBlockProps {
  code: string;
  label?: ReactNode;
  copyLabel?: ReactNode;
  copiedLabel?: ReactNode;
  className?: string;
}

/** A shell command or snippet with a one-click copy. */
export function CommandBlock({ code, label, copyLabel, copiedLabel, className }: CommandBlockProps) {
  return (
    <div className={cn("rui-cmd", className)}>
      <div className="rui-cmd__bar">
        <span>{label}</span>
        <CopyButton text={code} label={copyLabel} copiedLabel={copiedLabel} />
      </div>
      <pre className="rui-cmd__code">
        <code>{code}</code>
      </pre>
    </div>
  );
}
