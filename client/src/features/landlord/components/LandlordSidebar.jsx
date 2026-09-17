import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, FlaskConical } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import { NewActionMenu } from "@/components/layout/PortalQuickNav";
import { LANDLORD_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { buildPortalNav, buildNewActions } from "@/config/portalNav";
import { useAuth } from "@/hooks/useAuth";
import { useGetEtimsScopeQuery } from "@/features/landlord/etims/etimsApiSlice";
import { useGetLeasesQuery } from "@/features/landlord/leases/leaseApiSlice";
import { useDemoMode } from "@/features/landlord/useDemoMode";
import DemoModeEnterDialog from "@/features/landlord/components/DemoModeEnterDialog";

// Grouped navigation — see src/config/portalNav.jsx for the structure and why.
export default function LandlordSidebar({ isMobileOpen, onCloseMobile }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { isActive: isDemoActive, enter, exit, isEntering, isExiting } = useDemoMode();
  const [showEnterConfirm, setShowEnterConfirm] = useState(false);
  const { data: etimsScope } = useGetEtimsScopeQuery();
  const { data: leaseData } = useGetLeasesQuery({ status: "submitted" }, { pollingInterval: 120000 });

  // eTIMS links appear ONLY when an in-scope property has eTIMS switched on.
  const items = buildPortalNav(LANDLORD_ROUTES, {
    etims: Boolean(etimsScope?.enabled),
    leaseReviewCount: leaseData?.awaiting_review ?? 0,
  });

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.login);
  };

  return (
    <>
      <Sidebar
        items={items}
        isMobileOpen={isMobileOpen}
        onCloseMobile={onCloseMobile}
        topSlot={<NewActionMenu actions={buildNewActions(LANDLORD_ROUTES)} />}
        footer={
          <div className="space-y-2 px-1">
            <p className="truncate text-xs text-white/40">{user?.email}</p>
            <button
              onClick={() => (isDemoActive ? exit() : setShowEnterConfirm(true))}
              disabled={isEntering || isExiting}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/60 transition-colors hover:bg-white/5 hover:text-white"
            >
              <FlaskConical className="h-4 w-4" /> {isDemoActive ? "Exit demo mode" : "Try demo mode"}
            </button>
            <button
              onClick={handleLogout}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/60 transition-colors hover:bg-white/5 hover:text-white"
            >
              <LogOut className="h-4 w-4" /> Log out
            </button>
          </div>
        }
      />
      <DemoModeEnterDialog
        isOpen={showEnterConfirm}
        onClose={() => setShowEnterConfirm(false)}
        onConfirm={async () => {
          await enter();
          setShowEnterConfirm(false);
        }}
        isLoading={isEntering}
      />
    </>
  );
}
