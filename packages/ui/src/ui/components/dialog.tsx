import { createContext, useContext, useId, useMemo, useRef } from "react";
import type { HTMLAttributes, MouseEvent, ReactNode } from "react";
import { cn } from "../../lib/cn";
import { Portal, useModal } from "../../lib/overlay";

interface DialogContextValue {
  open: boolean;
  close: () => void;
  titleId: string;
  descriptionId: string;
}

const DialogContext = createContext<DialogContextValue | null>(null);

function useDialog(part: string): DialogContextValue {
  const value = useContext(DialogContext);
  if (!value) throw new Error(`<${part}> must be rendered inside <Dialog>`);
  return value;
}

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children?: ReactNode;
}

export function Dialog({ open, onOpenChange, children }: DialogProps) {
  const base = useId();
  const latest = useRef(onOpenChange);
  latest.current = onOpenChange;
  const value = useMemo<DialogContextValue>(
    () => ({
      open,
      close: () => latest.current(false),
      titleId: `${base}-title`,
      descriptionId: `${base}-desc`,
    }),
    [open, base],
  );
  return <DialogContext.Provider value={value}>{children}</DialogContext.Provider>;
}

export interface DialogContentProps extends HTMLAttributes<HTMLDivElement> {
  /** Set false for flows that must be answered (default: clicking outside closes). */
  dismissOnBackdrop?: boolean;
}

export function DialogContent({
  className,
  children,
  dismissOnBackdrop = true,
  ...rest
}: DialogContentProps) {
  const { open, close, titleId, descriptionId } = useDialog("DialogContent");
  const panel = useRef<HTMLDivElement>(null);
  useModal(open, close, panel);
  if (!open) return null;
  return (
    <Portal>
      <div
        className="rui-overlay"
        onMouseDown={(event: MouseEvent<HTMLDivElement>) => {
          if (dismissOnBackdrop && event.target === event.currentTarget) close();
        }}
      >
        <div
          ref={panel}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          tabIndex={-1}
          className={cn("rui-dialog", className)}
          {...rest}
        >
          {children}
        </div>
      </div>
    </Portal>
  );
}

export function DialogHeader({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rui-dialog__header", className)} {...rest} />;
}

export function DialogFooter({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rui-dialog__footer", className)} {...rest} />;
}

export function DialogTitle({ className, ...rest }: HTMLAttributes<HTMLHeadingElement>) {
  const { titleId } = useDialog("DialogTitle");
  return <h2 id={titleId} className={cn("rui-dialog__title", className)} {...rest} />;
}

export function DialogDescription({ className, ...rest }: HTMLAttributes<HTMLParagraphElement>) {
  const { descriptionId } = useDialog("DialogDescription");
  return <p id={descriptionId} className={cn("rui-dialog__desc", className)} {...rest} />;
}
