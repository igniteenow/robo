import { useCallback, useRef, useState } from "react";

export interface UseConfirmDeleteOptions<T> {
  /** Performs the deletion. Reject (throw) to signal failure. */
  onDelete: (id: T) => Promise<void> | void;
  onSuccess?: (id: T) => void;
  onError?: (error: unknown, id: T) => void;
}

export interface UseConfirmDeleteResult<T> {
  /** True while a confirmation is being asked for. */
  isOpen: boolean;
  /** The item awaiting confirmation, or null. */
  pendingId: T | null;
  isDeleting: boolean;
  requestDelete: (id: T) => void;
  cancel: () => void;
  confirm: () => Promise<void>;
}

/** Two-step delete: `requestDelete(id)` opens a confirmation, `confirm()` runs
 *  `onDelete`. Pair it with `<ConfirmDialog>`. The dialog stays open if the
 *  deletion fails so the user can retry or cancel. */
export function useConfirmDelete<T = string>(
  options: UseConfirmDeleteOptions<T>,
): UseConfirmDeleteResult<T> {
  const [pendingId, setPendingId] = useState<T | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  // Always call the latest callbacks without forcing callers to memoise them.
  const latest = useRef(options);
  latest.current = options;

  const requestDelete = useCallback((id: T): void => setPendingId(id), []);

  const cancel = useCallback((): void => {
    if (!isDeleting) setPendingId(null);
  }, [isDeleting]);

  const confirm = useCallback(async (): Promise<void> => {
    if (pendingId === null || isDeleting) return;
    const id = pendingId;
    setIsDeleting(true);
    try {
      await latest.current.onDelete(id);
      setPendingId(null);
      latest.current.onSuccess?.(id);
    } catch (error) {
      latest.current.onError?.(error, id);
    } finally {
      setIsDeleting(false);
    }
  }, [pendingId, isDeleting]);

  return { isOpen: pendingId !== null, pendingId, isDeleting, requestDelete, cancel, confirm };
}
