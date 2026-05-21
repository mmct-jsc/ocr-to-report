/**
 * Accessible Tabs primitive — keyboard-navigable, ARIA-correct.
 *
 * Hand-rolled rather than pulled from Radix to keep the dep tree
 * narrow. The component pair (``Tabs`` + ``TabsList`` + ``TabsTrigger``
 * + ``TabsPanel``) implements WAI-ARIA 1.2 "Tabs" pattern:
 *
 * * ``role="tablist"`` on the strip, ``role="tab"`` on each trigger,
 *   ``role="tabpanel"`` on each panel.
 * * ``aria-selected`` + ``aria-controls`` on the active trigger.
 * * Roving tabindex (active trigger ``tabindex=0``; others ``-1``).
 * * Arrow-Left / Arrow-Right move focus + change selection
 *   (activate-on-focus is the conventional choice for stateless tabs).
 * * Home / End jump to first / last trigger.
 *
 * Usage:
 *
 *     <Tabs value={tab} onValueChange={setTab} idPrefix="settings">
 *       <TabsList>
 *         <TabsTrigger value="general">General</TabsTrigger>
 *         <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
 *       </TabsList>
 *       <TabsPanel value="general">…</TabsPanel>
 *       <TabsPanel value="pipeline">…</TabsPanel>
 *     </Tabs>
 */

import {
  createContext,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
} from "react";

interface TabsContextValue {
  value: string;
  setValue: (v: string) => void;
  idPrefix: string;
  registerTrigger: (value: string, el: HTMLButtonElement | null) => void;
  triggerKeyDown: (event: KeyboardEvent<HTMLButtonElement>, value: string) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabs(): TabsContextValue {
  const ctx = useContext(TabsContext);
  if (ctx === null) {
    throw new Error("Tabs subcomponents must be used inside <Tabs>");
  }
  return ctx;
}

export interface TabsProps {
  value: string;
  onValueChange: (value: string) => void;
  /** Prefix for generated ids so multiple Tabs on one page don't collide. */
  idPrefix: string;
  children: ReactNode;
  className?: string;
}

export function Tabs({ value, onValueChange, idPrefix, children, className }: TabsProps) {
  // Stable ref map of value → trigger element. Used by the keyboard
  // handler to focus the next/prev trigger after arrow keys.
  const triggers = useRef<Map<string, HTMLButtonElement>>(new Map());
  // Insertion-ordered value list. Map preserves insertion order so
  // we can walk it for next/prev.
  const orderedValues = useRef<string[]>([]);

  const registerTrigger = useCallback((triggerValue: string, el: HTMLButtonElement | null) => {
    if (el === null) {
      triggers.current.delete(triggerValue);
      orderedValues.current = orderedValues.current.filter((v) => v !== triggerValue);
      return;
    }
    triggers.current.set(triggerValue, el);
    if (!orderedValues.current.includes(triggerValue)) {
      orderedValues.current.push(triggerValue);
    }
  }, []);

  const triggerKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>, fromValue: string) => {
      const values = orderedValues.current;
      const index = values.indexOf(fromValue);
      if (index === -1) return;

      let next: string | null = null;
      switch (event.key) {
        case "ArrowRight":
          next = values[(index + 1) % values.length] ?? null;
          break;
        case "ArrowLeft":
          next = values[(index - 1 + values.length) % values.length] ?? null;
          break;
        case "Home":
          next = values[0] ?? null;
          break;
        case "End":
          next = values[values.length - 1] ?? null;
          break;
        default:
          return;
      }
      if (next === null) return;
      event.preventDefault();
      onValueChange(next);
      // Defer focus so the activated trigger gets focus AFTER React
      // commits the tabindex change. Microtask is enough.
      queueMicrotask(() => triggers.current.get(next!)?.focus());
    },
    [onValueChange],
  );

  const ctx = useMemo<TabsContextValue>(
    () => ({
      value,
      setValue: onValueChange,
      idPrefix,
      registerTrigger,
      triggerKeyDown,
    }),
    [value, onValueChange, idPrefix, registerTrigger, triggerKeyDown],
  );

  return (
    <TabsContext.Provider value={ctx}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      role="tablist"
      className={
        className ??
        "flex items-center gap-1 border-b border-border mb-6 overflow-x-auto"
      }
    >
      {children}
    </div>
  );
}

export function TabsTrigger({
  value,
  children,
  className,
}: {
  value: string;
  children: ReactNode;
  className?: string;
}) {
  const ctx = useTabs();
  const selected = ctx.value === value;
  const triggerId = `${ctx.idPrefix}-tab-${value}`;
  const panelId = `${ctx.idPrefix}-panel-${value}`;
  return (
    <button
      type="button"
      role="tab"
      id={triggerId}
      aria-selected={selected}
      aria-controls={panelId}
      tabIndex={selected ? 0 : -1}
      ref={(el) => ctx.registerTrigger(value, el)}
      onClick={() => ctx.setValue(value)}
      onKeyDown={(e) => ctx.triggerKeyDown(e, value)}
      className={
        className ??
        [
          "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-t",
          selected
            ? "border-primary text-foreground"
            : "border-transparent text-muted-foreground hover:text-foreground",
        ].join(" ")
      }
    >
      {children}
    </button>
  );
}

export function TabsPanel({
  value,
  children,
  className,
}: {
  value: string;
  children: ReactNode;
  className?: string;
}) {
  const ctx = useTabs();
  const triggerId = `${ctx.idPrefix}-tab-${value}`;
  const panelId = `${ctx.idPrefix}-panel-${value}`;
  if (ctx.value !== value) return null;
  return (
    <div
      role="tabpanel"
      id={panelId}
      aria-labelledby={triggerId}
      tabIndex={0}
      className={className ?? "focus-visible:outline-none"}
    >
      {children}
    </div>
  );
}
