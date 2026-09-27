import { Link } from "react-router-dom";
import { MessageCircle } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import NotificationBell from "@/features/notifications/NotificationBell";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { useGetSmsBalanceQuery } from "@/features/landlord/communications/communicationApiSlice";

// Top bar for the landlord shell — account, SMS balance, notifications.
export default function LandlordNavbar() {
  const { user } = useAuth();
  // Live balance, not the copy taken at sign-in: that one never moved however
  // many messages went out, which looked like sends were not being charged.
  const { data: sms } = useGetSmsBalanceQuery(undefined, { pollingInterval: 60000, refetchOnFocus: true });

  return (
    <div className="hidden items-center justify-end gap-4 px-4 pt-4 lg:flex">
      <Link
        to={`/landlord/${LANDLORD_ROUTES.communications}?compose=sms`}
        className="glass flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/70 transition-colors hover:text-white"
      >
        <MessageCircle className="h-4 w-4 text-secondary" />
        <span data-testid="navbar-sms-balance">{sms?.sms_balance ?? user?.profile?.sms_balance ?? 0}</span> SMS left
      </Link>
      <NotificationBell notificationsPath={LANDLORD_ROUTES.notifications} />
      <div className="glass flex items-center gap-2 rounded-xl px-3 py-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-xs font-medium text-white">
          {(user?.company_name || user?.email || "L")[0].toUpperCase()}
        </span>
        <span className="text-sm text-white/80">{user?.company_name || user?.email}</span>
      </div>
    </div>
  );
}
