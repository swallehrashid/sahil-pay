import { useAuth } from "@/hooks/useAuth";
import NotificationBell from "@/features/notifications/NotificationBell";
import { TEAM_ROUTES } from "@/config/routePaths";

// Top bar for the team-member shell — account info + notifications, same shell pattern as LandlordNavbar.
export default function TeamMemberNavbar() {
  const { user } = useAuth();

  return (
    <div className="hidden items-center justify-end gap-4 px-4 pt-4 lg:flex">
      <NotificationBell notificationsPath={TEAM_ROUTES.notifications} />
      <div className="glass flex items-center gap-2 rounded-xl px-3 py-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-xs font-medium text-white">
          {(user?.first_name || user?.username || "T")[0].toUpperCase()}
        </span>
        <span className="text-sm text-white/80">{user?.username || user?.email}</span>
      </div>
    </div>
  );
}
