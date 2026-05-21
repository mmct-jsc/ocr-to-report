import {
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
} from "react";
import { createPortal } from "react-dom";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

/**
 * Modal confirmation dialog for destructive or otherwise-irreversible
 * actions. Replaces ``window.confirm()`` calls that fail WCAG 2.1
 * 4.1.2 (native confirm can't be styled, isn't announced reliably,
 * and can't carry side-effect context).
 *
 * Contract:
 *
 * * ``open`` controls visibility. Parent owns the state.
 * * ``onClose`` fires when the user dismisses (Esc, backdrop click,
 *   Cancel button). ``onConfirm`` fires only when the user presses
 *   the destructive button.
 * * ``title`` and ``description`` are wired to ``aria-labelledby`` and
 *   ``aria-describedby`` on the panel.
 * * Focus moves to the Cancel button on open (safer default than
 *   auto-focusing the destructive action). Returns to the previously
 *   focused element on close.
 * * Tab is trapped between Cancel and Confirm so keyboard users can't
 *   escape into the page-behind content while the dialog is open.
 *
 * Render via portal at ``document.body`` so the modal escapes any
 * ``transform``/``filter`` ancestor that would otherwise break
 * fixed-positioning.
 */

export interface AlertDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Visual tone of the confirm button. ``danger`` for irreversible /
   * destructive; ``primary`` for routine confirmations. */
  tone?: "danger" | "primary";
  /** Optional pending state — disables both buttons and labels the
   * confirm button as in-flight. */
  pending?: boolean;
}

export function AlertDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "danger",
  pending = false,
}: AlertDialogProps) {
  const titleId = useId();
  const descId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  // Capture the element that had focus before the dialog opened so we
  // can restore it on close. Without this, sighted keyboard users get
  // dropped at the top of the page.
  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement as HTMLElement | null;
    // Focus the safer choice first.
    cancelRef.current?.focus();
    return () => {
      previousFocus.current?.focus?.();
    };
  }, [open]);

  // Esc to dismiss + Tab to trap focus between Cancel and Confirm.
  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (!open) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const cancel = cancelRef.current;
      const confirm = confirmRef.current;
      if (!cancel || !confirm) return;
      const active = document.activeElement;
      if (e.shiftKey && active === cancel) {
        e.preventDefault();
        confirm.focus();
      } else if (!e.shiftKey && active === confirm) {
        e.preventDefault();
        cancel.focus();
      }
    },
    [open, onClose],
  );

  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onKey]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      data-testid="alert-dialog"
    >
      {/* Backdrop — clicking it dismisses the dialog. We intentionally
          don't double-handle the keyboard on the backdrop; the panel
          itself handles Esc. */}
      <button
        type="button"
        aria-label="Close dialog"
        className="absolute inset-0 bg-black/60 cursor-default"
        onClick={onClose}
        tabIndex={-1}
      />

      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        className={cn(
          "relative w-full max-w-md rounded-lg bg-card text-card-foreground shadow-xl",
          "border border-border",
          "animate-fade-in",
        )}
      >
        <div className="p-6">
          <div className="flex items-start gap-4">
            <div
              className={cn(
                "shrink-0 grid place-items-center h-10 w-10 rounded-full",
                tone === "danger" ? "bg-danger/10 text-danger" : "bg-primary/10 text-primary",
              )}
              aria-hidden
            >
              <AlertTriangle size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <h2 id={titleId} className="text-lg font-semibold tracking-tight">
                {title}
              </h2>
              <div id={descId} className="text-sm text-muted-foreground mt-2 leading-relaxed">
                {description}
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-3 bg-muted/30 border-t border-border rounded-b-lg">
          <Button
            ref={cancelRef}
            variant="outline"
            onClick={onClose}
            disabled={pending}
          >
            {cancelLabel}
          </Button>
          <Button
            ref={confirmRef}
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            loading={pending}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
