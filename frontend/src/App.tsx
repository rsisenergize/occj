import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { CaseListPage } from "./pages/CaseListPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { ApprovalsQueuePage } from "./pages/ApprovalsQueuePage";
import { LiveFeedPage } from "./pages/debug/LiveFeedPage";
import { TimelineExplorerPage } from "./pages/debug/TimelineExplorerPage";
import { ConflictsPage } from "./pages/debug/ConflictsPage";
import { PipelineHealthPage } from "./pages/debug/PipelineHealthPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  // Debug UI is internal tooling for verifying the ingestion pipeline, not
  // the investigator workspace -- gated the same way as "seed demo data".
  if (user.role !== "admin") return <Navigate to="/cases" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/cases" replace />} />
        <Route path="/cases" element={<CaseListPage />} />
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
        <Route path="/approvals" element={<ApprovalsQueuePage />} />
        <Route path="/debug/events" element={<RequireAdmin><LiveFeedPage /></RequireAdmin>} />
        <Route path="/debug/timeline" element={<RequireAdmin><TimelineExplorerPage /></RequireAdmin>} />
        <Route path="/debug/conflicts" element={<RequireAdmin><ConflictsPage /></RequireAdmin>} />
        <Route path="/debug/health" element={<RequireAdmin><PipelineHealthPage /></RequireAdmin>} />
      </Route>
      <Route path="*" element={<Navigate to="/cases" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
