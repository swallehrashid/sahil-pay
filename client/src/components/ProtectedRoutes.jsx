import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { usePermissions } from "@/hooks/usePermissions";
import { AUTH_ROUTES } from "@/config/routePaths";
import { roleHomePath } from "@/routes/roleRedirect";

// The spine of the four-portal separation. Checks auth + ROLE + PERMISSION, not merely
// "is logged in" — a team member without `invoices` access must never reach
// /team/invoices even by typing the URL directly. The backend still enforces every rule;
// this is the UI-side gate that keeps the wrong screens from ever rendering.
export default function ProtectedRoutes({ allowedRoles, requiredPermission }) {
  const { isAuthenticated, isHydrating, role } = useAuth();
  const { can } = usePermissions();
  const location = useLocation();

  if (isHydrating) return <RouteLoader />;

  if (!isAuthenticated) {
    const loginPath = allowedRoles?.length === 1 && allowedRoles[0] === "tenant" ? AUTH_ROUTES.tenantLogin : AUTH_ROUTES.login;
    return <Navigate to={loginPath} state={{ from: location }} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(role)) {
    return <Navigate to={roleHomePath(role)} replace />;
  }

  if (requiredPermission && !can(requiredPermission.module, requiredPermission.level)) {
    return <Navigate to={roleHomePath(role)} replace />;
  }

  return <Outlet />;
}

// Centered glassmorphic SahilPay mark shown during route transitions, lazy chunks, and
// while auth is hydrating — so the user is never shown a flash of unauthenticated content.
export function RouteLoader() {
  return (
    <div className="app-bg flex min-h-screen items-center justify-center">
      <div className="relative flex h-20 w-20 items-center justify-center">
        <span className="absolute inset-0 animate-pulse-glow rounded-full bg-secondary/40 blur-xl" />
        <span className="glass relative flex h-16 w-16 animate-spin-slow items-center justify-center rounded-full">
          <span className="text-sm font-light tracking-widest text-white">SP</span>
        </span>
      </div>
    </div>
  );
}
