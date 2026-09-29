import { createContext } from "react";
import type { ReactNode } from "react";

export interface PageHeaderContextValue {
  setAfterTitle: (node: ReactNode) => void;
  /**
   * Accepts a node, or an updater that receives the current node — use the
   * updater to clear only a node you own, so a late cleanup can't wipe the
   * buttons another page has already put in the slot.
   */
  setEnd: (node: ReactNode | ((current: ReactNode) => ReactNode)) => void;
  setTitle: (title: string | null) => void;
}

export const PageHeaderContext = createContext<PageHeaderContextValue | null>(
  null,
);
