import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
  /** Heading level. Defaults to ``2`` — matches the CardTitle default,
   * keeps the document outline h1 (PageHeader) → h2 (EmptyState) clean
   * when EmptyState is the only content of a Card without its own
   * CardTitle. Use ``3`` when nesting inside a Card that already has
   * a CardTitle. */
  level?: 2 | 3 | 4;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  level = 2,
}: EmptyStateProps) {
  const HeadingTag = (`h${level}` as "h2" | "h3" | "h4");
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center p-10",
        "border border-dashed border-border rounded-lg bg-muted/20",
        className,
      )}
    >
      {Icon && (
        <div className="rounded-full bg-muted p-3 mb-4">
          <Icon size={20} className="text-muted-foreground" aria-hidden />
        </div>
      )}
      <HeadingTag className="text-base font-semibold text-foreground">{title}</HeadingTag>
      {description && (
        <p className="text-sm text-muted-foreground mt-1.5 max-w-md">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
