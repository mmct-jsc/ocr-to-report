import { useEffect, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Upload,
  Briefcase,
  Webhook,
  ShieldCheck,
  BookTemplate,
  Settings as SettingsIcon,
  LogOut,
  Moon,
  Sun,
  Activity,
  Menu,
  X,
  Building2,
  ServerCog,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useAuth, useClient } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { ImpersonationBanner, TenantSwitcher } from "@/components/tenant-switcher";

const TENANT_NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/upload", label: "Process", icon: Upload },
  { to: "/jobs", label: "Jobs", icon: Briefcase },
  { to: "/webhooks", label: "Webhooks", icon: Webhook },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck },
  { to: "/templates", label: "Templates", icon: BookTemplate },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

const ADMIN_NAV = [
  { to: "/admin/system", label: "System", icon: ServerCog },
  { to: "/admin/tenants", label: "Tenants", icon: Building2 },
];

export function AppLayout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const { signOut, baseUrl } = useAuth();
  const client = useClient();
  const { theme, toggle } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [healthy, setHealthy] = useState<boolean | null>(null);

  // The current key has admin scope iff /v1/admin/system returns 200.
  // We probe once on mount; admin links only render on success.
  const adminProbe = useQuery({
    queryKey: ["admin", "probe"],
    queryFn: () => client.admin.system().then(() => true).catch(() => false),
    retry: false,
    staleTime: 60_000,
  });
  const isAdmin = adminProbe.data === true;

  // Esc closes the mobile sidebar — matches what every other overlay
  // (dialogs, dropdowns) does, so keyboard users have a uniform mental
  // model for "get out of this thing."
  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  useEffect(() => {
    let alive = true;
    const ping = async () => {
      try {
        const url = baseUrl.endsWith("/") ? `${baseUrl}v1/health` : `${baseUrl}/v1/health`;
        const r = await fetch(url, { method: "GET" });
        if (alive) setHealthy(r.ok);
      } catch {
        if (alive) setHealthy(false);
      }
    };
    ping();
    const t = window.setInterval(ping, 15_000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [baseUrl]);

  const handleSignOut = () => {
    signOut();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-screen flex bg-background">
      {/* sidebar */}
      <aside
        data-testid="sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-64 bg-card border-r border-border",
          "flex flex-col transition-transform duration-200 lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center gap-2 px-5 h-16 border-b border-border">
          <div
            className="h-8 w-8 rounded-lg bg-primary text-primary-foreground grid place-items-center text-sm font-bold"
            aria-hidden
          >
            OR
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold tracking-tight">OCR-to-Report</p>
            <p className="text-[11px] text-muted-foreground">Operations Console</p>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1 scrollbar-thin">
          {TENANT_NAV.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                    "transition-colors",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )
                }
              >
                <Icon size={16} aria-hidden />
                <span>{item.label}</span>
              </NavLink>
            );
          })}

          {isAdmin && (
            <>
              <p className="px-3 pt-5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Admin
              </p>
              {ADMIN_NAV.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                        "transition-colors",
                        isActive
                          ? "bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      )
                    }
                  >
                    <Icon size={16} aria-hidden />
                    <span>{item.label}</span>
                  </NavLink>
                );
              })}
            </>
          )}
        </nav>
        <div className="px-4 py-3 border-t border-border space-y-2 text-[11px] text-muted-foreground">
          <div className="flex items-center gap-2">
            <Activity size={12} aria-hidden className={healthy ? "text-success" : "text-danger"} />
            <span>
              {healthy === null
                ? "Checking…"
                : healthy
                  ? "API healthy"
                  : "API unreachable"}
            </span>
          </div>
          <p className="font-mono truncate">{baseUrl}</p>
        </div>
      </aside>

      {/* main area */}
      <div className="flex-1 lg:pl-64">
        <header className="sticky top-0 z-30 h-16 bg-card/80 backdrop-blur border-b border-border flex items-center px-4 lg:px-6 gap-3">
          <button
            type="button"
            onClick={() => setMobileOpen((o) => !o)}
            className="lg:hidden p-2 rounded-md hover:bg-muted"
            aria-label={mobileOpen ? "close menu" : "open menu"}
          >
            {mobileOpen ? <X size={18} aria-hidden /> : <Menu size={18} aria-hidden />}
          </button>
          <div className="flex-1" />
          <TenantSwitcher />
          <Link
            to="/upload"
            className="hidden md:inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium bg-primary text-primary-foreground hover:opacity-90"
          >
            <Upload size={14} aria-hidden /> New transcript
          </Link>
          <button
            type="button"
            onClick={toggle}
            className="p-2 rounded-md hover:bg-muted text-muted-foreground"
            aria-label="toggle theme"
          >
            {theme === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
          </button>
          <button
            type="button"
            onClick={handleSignOut}
            className="p-2 rounded-md hover:bg-muted text-muted-foreground"
            aria-label="sign out"
          >
            <LogOut size={16} aria-hidden />
          </button>
        </header>
        <ImpersonationBanner />
        {/* Width is route-controlled: list views (jobs, audit, tenants)
            get the full content width; narrow forms (upload, settings)
            wrap their own container in ``max-w-3xl mx-auto``. The old
            global ``max-w-7xl mx-auto`` fought the sidebar push on
            1280-1440 viewports — content centered on a non-centered
            canvas left awkward dead space on the right. */}
        <main className="px-4 lg:px-8 py-6 animate-fade-in">{children}</main>
      </div>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 mb-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
        {description && (
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}
