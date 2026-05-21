import { type HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/cn";

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...rest }, ref) => (
    // ``flex flex-col`` so CardContent (or any direct child marked
    // ``flex-1``) can stretch to fill the card's height when the
    // outer grid stretches mismatched-content cards to equal heights.
    // Without this, the shorter card has its content hugging the top
    // and a "dangling" empty area at the bottom of the card frame.
    <div
      ref={ref}
      className={cn("surface shadow-sm flex flex-col", className)}
      {...rest}
    />
  ),
);
Card.displayName = "Card";

export function CardHeader({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pt-5 pb-3 shrink-0", className)} {...rest} />;
}

interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement> {
  /** Heading level. Defaults to ``2`` so card sections sit one level under
   * the route's ``<h1>`` (rendered by ``PageHeader``). Override only when
   * a card is nested deeper in the heading outline. */
  level?: 2 | 3 | 4;
}

export function CardTitle({ className, level = 2, ...rest }: CardTitleProps) {
  const Tag = (`h${level}` as "h2" | "h3" | "h4");
  return (
    <Tag
      className={cn("text-base font-semibold tracking-tight text-foreground", className)}
      {...rest}
    />
  );
}

export function CardDescription({ className, ...rest }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground mt-1", className)} {...rest} />;
}

export function CardContent({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  // ``flex-1`` makes CardContent grow within the card's flex column so
  // short content centers within the stretched card rather than leaving
  // empty space at the bottom. Children with their own ``flex flex-col
  // items-center justify-center`` (EmptyState) center vertically; lists
  // and tables overflow naturally without changing.
  return <div className={cn("px-5 pb-5 flex-1", className)} {...rest} />;
}

export function CardFooter({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "shrink-0 px-5 py-3 border-t border-border bg-muted/30 flex items-center justify-end gap-2",
        className,
      )}
      {...rest}
    />
  );
}
