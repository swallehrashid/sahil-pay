import { useNavigate } from "react-router-dom";
import { LogOut } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import { NewActionMenu } from "@/components/layout/PortalQuickNav";
import { TEAM_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { buildPortalNav, buildNewActions, filterPortalNav } from "@/config/portalNav";
import { useAuth } from "@/hooks/useAuth";
import { usePermissions } from "@/hooks/usePermissions";
import { useGetEtimsScopeQuery } from "@/features/landlord/etims/etimsApiSlice";

// The same grouped navigation as the landlord's (src/config/portalNav.jsx),
// filtered to the modules this member may see — a hidden module never renders,
// and a group with nothing left in it disappears. The backend enforces the same
// permissions on every route independently.
export default function TeamMemberSidebar({ isMobileOpen, onCloseMobile }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { can } = usePermissions();
  const { data: etimsScope } = useGetEtimsScopeQuery();

  const canView = (module, requires) => can(module, requires || "view");
  const items = filterPortalNav(
    buildPortalNav(TEAM_ROUTES, { etims: Boolean(etimsScope?.enabled), isLandlord: false }),
    canView,
  );
  const actions = buildNewActions(TEAM_ROUTES).filter((a) => can(a.module, a.requires));

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.login);
  };

  return (
    <Sidebar
      items={items}
      isMobileOpen={isMobileOpen}
      onCloseMobile={onCloseMobile}
      topSlot={actions.length ? <NewActionMenu actions={actions} /> : null}
      footer={
        <div className="space-y-2 px-1">
          <p className="truncate text-xs text-white/40">{user?.email}</p>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/60 transition-colors hover:bg-white/5 hover:text-white"
          >
            <LogOut className="h-4 w-4" /> Log out
          </button>
        </div>
      }
    />
  );
}
