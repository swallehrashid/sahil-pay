import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import { ShieldAlert, LogOut } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { apiSlice } from "@/store/apiSlice";
import { getImpersonationTarget, clearImpersonationTarget } from "@/utils/impersonationStorage";
import { USER_ROLES } from "@/utils/constants";
import { ADMIN_ROUTES } from "@/config/routePaths";

// Shown across every landlord-portal page while a system_admin is operating a
// granted account (§10.5) — the admin-side counterpart to the landlord's own
// ImpersonationBanner, which warns THEM an admin session is live.
export default function AdminImpersonationBanner() {
  const { role } = useAuth();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const target = getImpersonationTarget();

  if (role !== USER_ROLES.SYSTEM_ADMIN || !target) return null;

  const handleExit = () => {
    clearImpersonationTarget();
    // Different impersonation targets must never share cached query results —
    // force every endpoint to refetch under whichever scope applies next.
    dispatch(apiSlice.util.resetApiState());
    navigate(ADMIN_ROUTES.impersonation, { replace: true });
  };

  return (
    <div className="mb-6 flex items-center justify-between gap-3 rounded-2xl border border-amber-400/40 bg-amber-400/15 px-4 py-3 text-sm text-amber-100 animate-fade-in-up">
      <div className="flex items-center gap-3">
        <ShieldAlert className="h-4 w-4 flex-shrink-0" />
        You are operating <strong>{target.companyName}</strong>&apos;s account as a SahilPay admin. Every action is audit-logged.
      </div>
      <button onClick={handleExit} className="flex items-center gap-1 whitespace-nowrap text-amber-100 hover:underline">
        <LogOut className="h-3.5 w-3.5" /> Exit
      </button>
    </div>
  );
}
