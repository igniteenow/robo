import { useId, useRef } from "react";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { Portal, useModal } from "../../lib/overlay";

export interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  /** Accessible name for the tap-outside-to-close area. */
  backdropDismissLabel?: string;
  className?: string;
  children?: ReactNode;
}

export function BottomSheet({
  open,
  onClose,
  title,
  backdropDismissLabel = "Close",
  className,
  children,
}: BottomSheetProps) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useModal(open, onClose, panel);
  if (!open) return null;
  return (
    <Portal>
      <div className="rui-overlay" data-sheet="true">
        <button
          type="button"
          tabIndex={-1}
          className="rui-backdrop-btn"
          aria-label={backdropDismissLabel}
          onClick={onClose}
        />
        <div
          ref={panel}
          role="dialog"
          aria-modal="true"
          aria-labelledby={title !== undefined ? titleId : undefined}
          tabIndex={-1}
          className={cn("rui-sheet", className)}
          style={{ position: "relative" }}
        >
          <div className="rui-sheet__grip" aria-hidden="true" />
          {title !== undefined && (
            <h2 id={titleId} className="rui-sheet__title">
              {title}
            </h2>
          )}
          {children}
        </div>
      </div>
    </Portal>
  );
}
