import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { AppLayout } from "@/components/layout";
import { LoginRoute } from "@/routes/login";
import { DashboardRoute } from "@/routes/dashboard";
import { UploadRoute } from "@/routes/upload";
import { JobsRoute } from "@/routes/jobs";
import { JobDetailRoute } from "@/routes/job-detail";
import { WebhooksRoute } from "@/routes/webhooks";
import { ComplianceRoute } from "@/routes/compliance";
import { TemplatesRoute } from "@/routes/templates";
import { SettingsRoute } from "@/routes/settings";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { client } = useAuth();
  const location = useLocation();
  if (!client) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <AppLayout>{children}</AppLayout>;
}

export function App() {
  const { client } = useAuth();
  return (
    <Routes>
      <Route
        path="/login"
        element={client ? <Navigate to="/dashboard" replace /> : <LoginRoute />}
      />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <DashboardRoute />
          </RequireAuth>
        }
      />
      <Route
        path="/upload"
        element={
          <RequireAuth>
            <UploadRoute />
          </RequireAuth>
        }
      />
      <Route
        path="/jobs"
        element={
          <RequireAuth>
            <JobsRoute />
          </RequireAuth>
        }
      />
      <Route
        path="/jobs/:jobId"
        element={
          <RequireAuth>
            <JobDetailRoute />
          </RequireAuth>
        }
      />
      <Route
        path="/webhooks"
        element={
          <RequireAuth>
            <WebhooksRoute />
          </RequireAuth>
        }
      />
      <Route
        path="/compliance"
        element={
          <RequireAuth>
            <ComplianceRoute />
          </RequireAuth>
        }
      />
      <Route
        path="/templates"
        element={
          <RequireAuth>
            <TemplatesRoute />
          </RequireAuth>
        }
      />
      <Route
        path="/settings"
        element={
          <RequireAuth>
            <SettingsRoute />
          </RequireAuth>
        }
      />
      <Route path="/" element={<Navigate to={client ? "/dashboard" : "/login"} replace />} />
      <Route path="*" element={<Navigate to={client ? "/dashboard" : "/login"} replace />} />
    </Routes>
  );
}
