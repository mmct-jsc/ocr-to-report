import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "success" | "warning" | "danger" | "info";
interface Toast {
  id: number;
  tone: Tone;
  title: string;
  description?: string;
}

interface ToastContextValue {
  push: (t: Omit<Toast, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  warn: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const ICON: Record<Tone, typeof CheckCircle2> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
  info: Info,
};

const TONE_CLASS: Record<Tone, string> = {
  success: "border-success/30 text-success",
  warning: "border-warning/30 text-warning",
  danger: "border-danger/30 text-danger",
  info: "border-primary/30 text-primary",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback(
    (id: number) => setToasts((cur) => cur.filter((t) => t.id !== id)),
    [],
  );

  const push = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = Date.now() + Math.random();
      setToasts((cur) => [...cur, { ...t, id }]);
      // Error toasts stay until dismissed. A user editing a long form
      // can miss a 5-second flash; for a destructive-action failure
      // ("the API rejected this upload because…") sticky beats
      // ephemeral. Non-error toasts auto-clear at 5s as before.
      if (t.tone !== "danger") {
        window.setTimeout(() => remove(id), 5000);
      }
    },
    [remove],
  );

  const value: ToastContextValue = useMemo(
    () => ({
      push,
      success: (title, description) => push({ tone: "success", title, description }),
      error: (title, description) => push({ tone: "danger", title, description }),
      warn: (title, description) => push({ tone: "warning", title, description }),
      info: (title, description) => push({ tone: "info", title, description }),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed top-4 right-4 z-[60] flex flex-col gap-2 w-[360px]"
        role="region"
        aria-label="notifications"
      >
        {toasts.map((t) => {
          const Icon = ICON[t.tone];
          return (
            <div
              key={t.id}
              role={t.tone === "danger" ? "alert" : "status"}
              aria-live={t.tone === "danger" ? "assertive" : "polite"}
              className={cn(
                "pointer-events-auto surface shadow-lg flex gap-3 px-4 py-3 animate-slide-up",
                "border-l-4",
                TONE_CLASS[t.tone],
              )}
            >
              <Icon size={18} className="mt-0.5 shrink-0" aria-hidden />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-foreground">{t.title}</p>
                {t.description && (
                  <p className="text-xs text-muted-foreground mt-0.5 break-words">
                    {t.description}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => remove(t.id)}
                className="text-muted-foreground hover:text-foreground"
                aria-label="dismiss"
              >
                <X size={14} aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast requires <ToastProvider>");
  return ctx;
}
