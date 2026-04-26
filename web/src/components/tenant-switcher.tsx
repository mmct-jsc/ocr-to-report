import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Building2, Eye, EyeOff } from "lucide-react";
import { useAuth, useClient } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { cn } from "@/lib/cn";

/**
 * Topbar dropdown that lets an admin switch the tenant context for
 * every tenant-scoped page (dashboard, jobs, webhooks, compliance,
 * usage). Only renders when the calling key has admin scope.
 *
 * Implementation:
 * - Lists all tenants via /v1/admin/tenants.
 * - Selecting a row sets `actingTenantId` in AuthContext, which
 *   rebuilds the SDK Client so the next request carries
 *   `X-Acting-Tenant-Id`.
 * - Invalidates every active query so the just-rendered dashboard
 *   refetches with the new tenant context.
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

  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

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

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!isAdmin) return null;

  const list = tenants.data ?? [];
  const acting = list.find((t) => t.id === actingTenantId);
  const label = actingTenantId
    ? acting
      ? acting.name
      : actingTenantId.slice(0, 8) + "…"
    : "(home tenant)";

  const switchTo = (id: string | null) => {
    setActingTenantId(id);
    // Update the live Client too so in-flight callers see it instantly.
    client.setActingTenantId(id);
    setOpen(false);
    qc.invalidateQueries();
    toast.info(
      id ? `Viewing ${list.find((t) => t.id === id)?.name ?? id}` : "Back to home tenant",
    );
  };

  return (
    <div className="relative" ref={ref} data-testid="tenant-switcher">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-2 h-8 px-3 rounded-md text-sm font-medium",
          "border border-border hover:bg-muted transition-colors max-w-[260px]",
          actingTenantId ? "border-warning/40 text-warning" : "text-foreground",
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {actingTenantId ? <Eye size={14} /> : <EyeOff size={14} />}
        <span className="truncate">{label}</span>
        <ChevronDown size={14} className="opacity-60" />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute right-0 mt-1.5 w-72 max-h-[420px] overflow-y-auto z-40 surface shadow-lg p-1"
        >
          <button
            type="button"
            onClick={() => switchTo(null)}
            className={cn(
              "w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm text-left",
              "hover:bg-muted",
              !actingTenantId && "bg-muted",
            )}
          >
            <Building2 size={14} className="text-muted-foreground" />
            <span className="flex-1">Home tenant</span>
            {!actingTenantId && (
              <span className="text-[10px] uppercase text-muted-foreground">current</span>
            )}
          </button>
          <div className="my-1 border-t border-border" />
          {tenants.isLoading ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">Loading…</p>
          ) : list.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">No other tenants.</p>
          ) : (
            <ul>
              {list.map((t) => {
                const selected = t.id === actingTenantId;
                return (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => switchTo(t.id)}
                      className={cn(
                        "w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm text-left",
                        "hover:bg-muted",
                        selected && "bg-muted",
                      )}
                    >
                      <Building2 size={14} className="text-muted-foreground" />
                      <div className="flex-1 min-w-0">
                        <p className="truncate font-medium">{t.name}</p>
                        <p className="text-[11px] text-muted-foreground font-mono truncate">
                          {t.slug} · sla {t.sla_tier}
                        </p>
                      </div>
                      {selected && (
                        <span className="text-[10px] uppercase text-muted-foreground">
                          current
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
