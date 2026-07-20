import { useAuth } from "@/hooks/useAuth";
import NotificationBell from "@/features/notifications/NotificationBell";
import { ADMIN_ROUTES } from "@/config/routePaths";

export default function AdminNavbar() {
  const { user } = useAuth();
  return (
    <div className="hidden items-center justify-end gap-4 px-4 pt-4 lg:flex">
      <NotificationBell notificationsPath={ADMIN_ROUTES.notifications} />
      <div className="glass flex items-center gap-2 rounded-xl px-3 py-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-third text-xs font-medium text-white">
          {(user?.first_name || "A")[0].toUpperCase()}
        </span>
        <span className="text-sm text-white/80">{user?.email}</span>
      </div>
    </div>
  );
}
