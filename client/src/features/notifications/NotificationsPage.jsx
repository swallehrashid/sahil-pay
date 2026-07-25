import { useState, useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CheckCheck, Send, ExternalLink } from "lucide-react";
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
  const [searchParams] = useSearchParams();
  const focusId = searchParams.get("focus");
  const { role } = useAuth();
  const [page, setPage] = useState(1);
  const { data, isLoading } = useGetNotificationsQuery({ page, per_page: 20 });
  const [markRead] = useMarkNotificationReadMutation();
  const [markAllRead, { isLoading: isMarkingAll }] = useMarkAllNotificationsReadMutation();

  // The currently highlighted (clicked) notification — from the ?focus deep-link
  // or from clicking a row here.
  const [selectedId, setSelectedId] = useState(focusId ? Number(focusId) : null);
  const rowRefs = useRef({});

  const notifications = data?.notifications ?? [];
  const sendPath =
    role === USER_ROLES.SYSTEM_ADMIN ? ADMIN_ROUTES.notificationsSend
    : role === USER_ROLES.LANDLORD || role === USER_ROLES.PROPERTY_MANAGER ? LANDLORD_ROUTES.notificationsSend
    : null;

  // Deep-link from the bell dropdown: scroll the focused notification into view
  // and mark it read (it's now been "opened").
  useEffect(() => {
    if (!focusId || isLoading) return;
    const id = Number(focusId);
    setSelectedId(id);
    const el = rowRefs.current[id];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    const note = notifications.find((n) => n.id === id);
    if (note && !note.is_read) markRead(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId, isLoading, data]);

  // Clicking a notification in the list just highlights it (marks read); it does
  // NOT navigate away. The linked entity, if any, is reachable via the arrow.
  const handleOpen = (note) => {
    setSelectedId(note.id);
    if (!note.is_read) markRead(note.id);
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
            <div
              key={note.id}
              ref={(el) => { rowRefs.current[note.id] = el; }}
              onClick={() => handleOpen(note)}
              className={clsx(
                "flex w-full cursor-pointer items-start gap-3 px-5 py-4 text-left transition-colors hover:bg-white/5",
                !note.is_read && "bg-white/[0.03]",
                selectedId === note.id && "bg-secondary/10 ring-1 ring-inset ring-secondary/40"
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
              {note.link && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); if (!note.is_read) markRead(note.id); navigate(note.link); }}
                  title="Open related page"
                  className="mt-0.5 flex-shrink-0 rounded-lg p-1.5 text-white/40 transition-colors hover:bg-white/10 hover:text-white"
                >
                  <ExternalLink className="h-4 w-4" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {data && (
        <Pagination page={data.current_page} perPage={20} total={data.total} onPageChange={setPage} />
      )}
    </div>
  );
}
