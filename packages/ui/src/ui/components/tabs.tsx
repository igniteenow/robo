import { createContext, useContext, useId, useMemo, useState } from "react";
import type { ButtonHTMLAttributes, HTMLAttributes, MouseEvent } from "react";
import { cn } from "../../lib/cn";

interface TabsContextValue {
  value: string;
  select: (value: string) => void;
  base: string;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabs(part: string): TabsContextValue {
  const value = useContext(TabsContext);
  if (!value) throw new Error(`<${part}> must be rendered inside <Tabs>`);
  return value;
}

export interface TabsProps extends Omit<HTMLAttributes<HTMLDivElement>, "onChange" | "defaultValue"> {
  /** Controlled selection. Omit and use `defaultValue` for uncontrolled. */
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
}

export function Tabs({ value, defaultValue = "", onValueChange, children, ...rest }: TabsProps) {
  const [inner, setInner] = useState(defaultValue);
  const base = useId();
  const current = value ?? inner;
  const context = useMemo<TabsContextValue>(
    () => ({
      value: current,
      base,
      select: (next) => {
        if (value === undefined) setInner(next);
        onValueChange?.(next);
      },
    }),
    [current, base, value, onValueChange],
  );
  return (
    <TabsContext.Provider value={context}>
      <div {...rest}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div role="tablist" className={cn("rui-tabs__list", className)} {...rest} />;
}

export interface TabsTriggerProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "value"> {
  value: string;
}

export function TabsTrigger({ value, className, onClick, ...rest }: TabsTriggerProps) {
  const tabs = useTabs("TabsTrigger");
  const selected = tabs.value === value;
  return (
    <button
      type="button"
      role="tab"
      id={`${tabs.base}-tab-${value}`}
      aria-controls={`${tabs.base}-panel-${value}`}
      aria-selected={selected}
      tabIndex={selected ? 0 : -1}
      className={cn("rui-tab", className)}
      onClick={(event: MouseEvent<HTMLButtonElement>) => {
        onClick?.(event);
        if (!event.defaultPrevented) tabs.select(value);
      }}
      {...rest}
    />
  );
}

export interface TabsContentProps extends HTMLAttributes<HTMLDivElement> {
  value: string;
}

export function TabsContent({ value, ...rest }: TabsContentProps) {
  const tabs = useTabs("TabsContent");
  if (tabs.value !== value) return null;
  return (
    <div
      role="tabpanel"
      id={`${tabs.base}-panel-${value}`}
      aria-labelledby={`${tabs.base}-tab-${value}`}
      tabIndex={0}
      {...rest}
    />
  );
}
