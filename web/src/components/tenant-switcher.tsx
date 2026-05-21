import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Building2, Eye, EyeOff } from "lucide-react";
import { useAuth, useClient } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { cn } from "@/lib/cn";

/**
 * Topbar dropdown that lets an admin switch the tenant context for
 * every tenant-scoped page. Only renders when the calling key has
 * admin scope.
 *
 * A11y contract (verified by Playwright + axe-core in CI):
 *
 * * Trigger has ``aria-haspopup="menu"``, ``aria-expanded``,
 *   ``aria-controls`` linking to the menu's id.
 * * Panel has ``role="menu"`` + ``aria-labelledby`` referencing the
 *   trigger.
 * * Each row has ``role="menuitem"``; the active row carries
 *   ``aria-current="true"``.
 * * Keyboard:
 *   - ``Enter`` / ``Space`` on the trigger opens AND focuses the first
 *     menu item.
 *   - ``ArrowDown`` / ``ArrowUp`` cycle through items.
 *   - ``Home`` / ``End`` jump to first / last item.
 *   - ``Esc`` closes the menu AND returns focus to the trigger.
 *   - ``Tab`` closes the menu (matches WAI-ARIA menu pattern; users
 *     leave a menu via Esc or by completing an action).
 *
 * Visual states:
 *
 * * Default (acting on home tenant): muted border, ``EyeOff`` icon.
 * * Impersonating: filled warning chip (white-on-warning) with
 *   ``Eye`` icon and the target tenant name in bold. Paired with
 *   the ``<ImpersonationBanner>`` rendered globally by AppLayout so
 *   the operator never loses track of context.
 */

export function TenantSwitcher() {
  const { client } = useAuth();
  return client ? <Inner /> : null;
}

function Inner() {
  const client = useClient();
  const { actingTenantId, setActingTenantId } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();

  const triggerId = useId();
  const menuId = useId();

  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  // ArrowUp on the trigger opens the menu AND focuses the last row.
  // When tenants are still loading we only have rows[0] ("Home tenant"),
  // so the "focus last" intent has to survive until the tenants list
  // arrives. Stored as a ref (not state) so it doesn't trigger renders.
  const pendingFocusLast = useRef(false);

  // Probe admin scope (cached by react-query under ['admin','probe']).
  const adminProbe = useQuery({
    queryKey: ["admin", "probe"],
    queryFn: () => client.admin.system().then(() => true).catch(() => false),
    retry: false,
    staleTime: 60_000,
  });
  const isAdmin = adminProbe.data === true;

  const tenants = useQuery({
    queryKey: ["admin", "tenants", "switcher"],
    queryFn: () => client.admin.listTenants(),
    enabled: isAdmin,
    staleTime: 30_000,
  });

  const list = tenants.data ?? [];
  // The first row is always "Home tenant"; the tenant list is offset by 1.
  const rows: Array<{ id: string | null; name: string; subtitle?: string }> = [
    { id: null, name: "Home tenant" },
    ...list.map((t) => ({ id: t.id, name: t.name, subtitle: `${t.slug} · sla ${t.sla_tier}` })),
  ];
  const acting = list.find((t) => t.id === actingTenantId);
  const label = actingTenantId
    ? acting
      ? acting.name
      : actingTenantId.slice(0, 8) + "…"
    : "Home tenant";

  // ─── Imperative open/close + focus management ────────────────
  const closeAndReturnFocus = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  // Regular function, not useCallback — ``rows`` is a fresh array literal
  // every render so a memoized callback would re-create each time anyway.
  // Inline handlers re-read it correctly each render.
  const openMenu = () => {
    setOpen(true);
    setActiveIndex(rows.findIndex((r) => r.id === actingTenantId) ?? 0);
  };

  // Focus the active menuitem on open + when activeIndex changes.
  useEffect(() => {
    if (!open) return;
    const target = itemRefs.current[activeIndex];
    if (target) target.focus();
  }, [open, activeIndex]);

  // ArrowUp-on-trigger "focus last" intent — fires once the tenants
  // list has loaded. Without this, a fresh page load + ArrowUp would
  // focus row 0 (the only row at that instant) instead of the last
  // tenant. We watch rows.length so the deferred focus lands once the
  // query resolves.
  useEffect(() => {
    if (!open || !pendingFocusLast.current) return;
    if (rows.length <= 1) return; // tenants not loaded yet — keep waiting
    pendingFocusLast.current = false;
    setActiveIndex(rows.length - 1);
  }, [open, rows.length]);

  // Close on outside click. Keyboard close is handled inline in
  // onKeyDown so we can preventDefault and not leak Esc to ancestors.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  if (!isAdmin) return null;

  const switchTo = (id: string | null) => {
    setActingTenantId(id);
    // Update the live Client too so in-flight callers see it instantly.
    client.setActingTenantId(id);
    closeAndReturnFocus();
    qc.invalidateQueries();
    const name = id ? list.find((t) => t.id === id)?.name ?? id : null;
    toast.info(
      name ? `Now acting as ${name}` : "Returned to home tenant",
      name ? "Every request is audited on the target tenant." : undefined,
    );
  };

  // ─── Trigger keyboard ────────────────────────────────────────
  const onTriggerKey = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openMenu();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      // Set the intent first so the focus-last effect picks it up
      // even when ``tenants`` is still loading. Once rows.length > 1
      // the effect at the top of the function fires and lands focus
      // on the last row.
      pendingFocusLast.current = true;
      openMenu();
    }
  };

  // ─── Menu keyboard ───────────────────────────────────────────
  const onMenuKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    switch (e.key) {
      case "Escape":
        e.preventDefault();
        closeAndReturnFocus();
        return;
      case "Tab":
        // WAI-ARIA: Tab in a menu closes the menu. Don't preventDefault
        // so the browser advances focus to the next page tabstop.
        setOpen(false);
        return;
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % rows.length);
        return;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((i) => (i - 1 + rows.length) % rows.length);
        return;
      case "Home":
        e.preventDefault();
        setActiveIndex(0);
        return;
      case "End":
        e.preventDefault();
        setActiveIndex(rows.length - 1);
        return;
    }
  };

  return (
    <div className="relative" ref={wrapRef} data-testid="tenant-switcher">
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={onTriggerKey}
        className={cn(
          "inline-flex items-center gap-2 h-8 px-3 rounded-md text-sm font-medium",
          "transition-colors max-w-[260px]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
          actingTenantId
            ? "bg-warning text-white hover:opacity-90 shadow-sm font-semibold"
            : "border border-border text-foreground hover:bg-muted",
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
      >
        {actingTenantId ? <Eye size={14} aria-hidden /> : <EyeOff size={14} aria-hidden />}
        <span className="truncate">{label}</span>
        <ChevronDown size={14} aria-hidden className="opacity-70" />
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-labelledby={triggerId}
          onKeyDown={onMenuKey}
          className="absolute right-0 mt-1.5 w-72 max-h-[420px] overflow-y-auto z-40 surface shadow-lg p-1"
        >
          {tenants.isLoading ? (
            <p className="px-3 py-2 text-xs text-muted-foreground" role="status">
              Loading tenants…
            </p>
          ) : (
            rows.map((row, idx) => {
              const isCurrent = row.id === actingTenantId;
              const isSeparatorBefore = idx === 1;
              return (
                <div key={row.id ?? "home"}>
                  {isSeparatorBefore && (
                    <div role="separator" className="my-1 border-t border-border" />
                  )}
                  <button
                    ref={(el) => {
                      itemRefs.current[idx] = el;
                    }}
                    type="button"
                    role="menuitem"
                    tabIndex={activeIndex === idx ? 0 : -1}
                    aria-current={isCurrent ? "true" : undefined}
                    onClick={() => switchTo(row.id)}
                    className={cn(
                      "w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm text-left",
                      "focus:outline-none focus:bg-muted",
                      "hover:bg-muted",
                      isCurrent && "bg-muted",
                    )}
                  >
                    <Building2
                      size={14}
                      aria-hidden
                      className="text-muted-foreground shrink-0"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="truncate font-medium">{row.name}</p>
                      {row.subtitle && (
                        <p className="text-[11px] text-muted-foreground font-mono truncate">
                          {row.subtitle}
                        </p>
                      )}
                    </div>
                    {isCurrent && (
                      <span className="text-[10px] uppercase text-muted-foreground shrink-0">
                        current
                      </span>
                    )}
                  </button>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Sticky banner across the top of ``<main>`` when an admin is acting
 * on a tenant other than their home tenant. Provides ambient context
 * so the operator can't forget they're impersonating mid-task.
 *
 * Renders nothing when ``actingTenantId`` is null. Rendered by
 * AppLayout, not the TenantSwitcher, so the banner is independent of
 * the dropdown's open/closed state.
 */
export function ImpersonationBanner() {
  const { client, actingTenantId } = useAuth();

  // Shares the queryKey with ``TenantSwitcher`` so react-query dedupes
  // the actual /v1/admin/tenants request. The two ``enabled`` predicates
  // diverge — switcher fires on admin, banner fires on impersonation —
  // so on a cold load with an admin who's already impersonating, the
  // banner can fire first (admin probe still pending). React-query
  // hands the second caller the cached result, no ping-pong.
  const tenants = useQuery({
    queryKey: ["admin", "tenants", "switcher"],
    queryFn: () => client!.admin.listTenants(),
    enabled: !!client && !!actingTenantId,
    staleTime: 30_000,
  });

  if (!actingTenantId) return null;
  const acting = tenants.data?.find((t) => t.id === actingTenantId);
  const name = acting?.name ?? `${actingTenantId.slice(0, 8)}…`;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "sticky top-16 z-20 bg-warning text-white shadow-sm",
        "flex items-center gap-3 px-4 lg:px-8 py-2 text-sm",
      )}
    >
      <Eye size={16} aria-hidden className="shrink-0" />
      <p className="flex-1">
        Acting as <strong className="font-semibold">{name}</strong> — every
        request is audited on the target tenant.
      </p>
    </div>
  );
}
