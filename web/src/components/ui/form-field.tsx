import { type ReactNode, useId } from "react";
import { AlertCircle } from "lucide-react";
import { Label } from "@/components/ui/input";
import { cn } from "@/lib/cn";

/**
 * Wraps a single form control with its label, optional helper text,
 * and an inline error message. Auto-wires the accessibility plumbing
 * that every form should have:
 *
 * * ``htmlFor`` on the label ↔ ``id`` on the input — clicking the
 *   label focuses the input; SR announces the label when the input
 *   takes focus.
 * * ``aria-invalid={!!error}`` on the input so the input's border
 *   turns red AND screen readers announce "invalid".
 * * ``aria-describedby`` linking the input to the error (when set)
 *   or the helper text (otherwise). SR announces the message on
 *   focus or status-change.
 * * The error ``<p>`` carries ``role="alert"`` so it's announced on
 *   appearance.
 *
 * The render-prop form is mandatory: callers receive the wired
 * ``{ id, "aria-invalid", "aria-describedby" }`` object and spread it
 * onto whichever element should advertise the error state. This is
 * the only shape that works correctly when the input is wrapped (e.g.
 * with an icon decoration inside a ``<div className="relative">``).
 * ``cloneElement`` would target the wrapper, not the input.
 */

export interface FormFieldAriaProps {
  id: string;
  "aria-invalid"?: true;
  "aria-describedby"?: string;
}

export interface FormFieldProps {
  label: string;
  /** Visible secondary instruction (e.g. "Use the same URL across
   * dev + prod"). Replaced by the error message when ``error`` is set. */
  helper?: ReactNode;
  /** Field-level error. Drives ``aria-invalid`` + the inline message. */
  error?: string | null;
  /** Force-set the id (otherwise generated via useId). */
  htmlFor?: string;
  /** Whether the label should be visually hidden (still in the DOM
   * for SR). Useful when the field is in a tight UI like a filter row. */
  visuallyHidden?: boolean;
  children: (ariaProps: FormFieldAriaProps) => ReactNode;
}

export function FormField({
  label,
  helper,
  error,
  htmlFor,
  visuallyHidden,
  children,
}: FormFieldProps) {
  const fallbackId = useId();
  const id = htmlFor ?? fallbackId;
  const errorId = `${id}-error`;
  const helperId = `${id}-helper`;

  // Pick the describedby target: error wins over helper. If neither
  // is set we omit the attribute so screen readers don't announce a
  // hanging empty reference.
  const describedBy = error ? errorId : helper ? helperId : undefined;

  const ariaProps: FormFieldAriaProps = {
    id,
    ...(error ? { "aria-invalid": true as const } : {}),
    ...(describedBy ? { "aria-describedby": describedBy } : {}),
  };

  return (
    <div className="space-y-1.5">
      <Label
        htmlFor={id}
        className={cn(visuallyHidden && "sr-only")}
      >
        {label}
      </Label>
      {children(ariaProps)}
      {error ? (
        <p
          id={errorId}
          role="alert"
          className="flex items-start gap-1.5 text-xs text-danger"
        >
          <AlertCircle size={12} aria-hidden className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </p>
      ) : helper ? (
        <p id={helperId} className="text-[11px] text-muted-foreground">
          {helper}
        </p>
      ) : null}
    </div>
  );
}
