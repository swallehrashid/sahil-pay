import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCheck, Send } from "lucide-react";
import clsx from "clsx";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Pagination from "@/components/ui/Pagination";
import EmptyState from "@/components/ui/EmptyState";
import {
  useGetNotificationsQuery, useMarkNotificationReadMutation, useMarkAllNotificationsReadMutation,
} from "./notificationApiSlice";
import { formatDateTime } from "@/utils/dateFormatter";
import { useAuth } from "@/hooks/useAuth";
import { USER_ROLES } from "@/utils/constants";
import { ADMIN_ROUTES, LANDLORD_ROUTES } from "@/config/routePaths";

// Full notification history for whichever role is logged in — the backend
// scopes everything to the caller's own recipient_user_id, so this single
// page works unmodified across all four portals. Only admins/landlords get
// a "Send" shortcut — team members and tenants can only receive.
export default function NotificationsPage() {
  const navigate = useNavigate();
  const { role } = useAuth();
  const [page, setPage] = useState(1);
  const { data, isLoading } = useGetNotificationsQuery({ page, per_page: 20 });
  const [markRead] = useMarkNotificationReadMutation();
  const [markAllRead, { isLoading: isMarkingAll }] = useMarkAllNotificationsReadMutation();

  const notifications = data?.notifications ?? [];
  const sendPath =
    role === USER_ROLES.SYSTEM_ADMIN ? ADMIN_ROUTES.notificationsSend
    : role === USER_ROLES.LANDLORD || role === USER_ROLES.PROPERTY_MANAGER ? LANDLORD_ROUTES.notificationsSend
    : null;

  const handleOpen = (note) => {
    if (!note.is_read) markRead(note.id);
    if (note.link) navigate(note.link);
  };

  return (
    <div>
      <PageHeader
        title="Notifications"
        subtitle="Everything sent to your account"
        actions={
          <>
            {sendPath && (
              <Button variant="ghost" leftIcon={<Send className="h-4 w-4" />} onClick={() => navigate(sendPath)}>
                Send notification
              </Button>
            )}
            <Button variant="ghost" leftIcon={<CheckCheck className="h-4 w-4" />} isLoading={isMarkingAll} onClick={() => markAllRead()}>
              Mark all read
            </Button>
          </>
        }
      />

      {isLoading ? (
        <p className="text-sm text-white/50">Loading…</p>
      ) : notifications.length === 0 ? (
        <EmptyState title="No notifications" description="You're all caught up." />
      ) : (
        <div className="glass divide-y divide-white/5 overflow-hidden">
          {notifications.map((note) => (
            <button
              key={note.id}
              onClick={() => handleOpen(note)}
              className={clsx(
                "flex w-full items-start gap-3 px-5 py-4 text-left transition-colors hover:bg-white/5",
                !note.is_read && "bg-white/[0.03]"
              )}
            >
              {!note.is_read && <span className="mt-2 h-2 w-2 flex-shrink-0 rounded-full bg-secondary" />}
              <div className={clsx("min-w-0 flex-1", note.is_read && "pl-5")}>
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium text-white">{note.title}</p>
                  <p className="flex-shrink-0 text-xs text-white/40">{formatDateTime(note.created_at)}</p>
                </div>
                <p className="mt-1 text-sm text-white/60">{note.body}</p>
              </div>
            </button>
          ))}
        </div>
      )}

      {data && (
        <Pagination page={data.current_page} perPage={20} total={data.total} onPageChange={setPage} />
      )}
    </div>
  );
}
