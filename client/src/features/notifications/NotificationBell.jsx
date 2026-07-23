import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck } from "lucide-react";
import clsx from "clsx";
import {
  useGetUnreadCountQuery, useGetNotificationsQuery,
  useMarkNotificationReadMutation, useMarkAllNotificationsReadMutation,
} from "./notificationApiSlice";
import { formatDateTime } from "@/utils/dateFormatter";

// Shared across all four portal navbars — polls unread count, shows the 5
// most recent notifications, marks-as-read on click (and deep-links via
// notification.link if present), with a "Mark all read" shortcut.
export default function NotificationBell({ notificationsPath }) {
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef(null);

  const { data: unreadData } = useGetUnreadCountQuery(undefined, { pollingInterval: 30000 });
  const { data, isLoading } = useGetNotificationsQuery({ per_page: 5 }, { skip: !isOpen });
  const [markRead] = useMarkNotificationReadMutation();
  const [markAllRead] = useMarkAllNotificationsReadMutation();

  const unreadCount = unreadData?.unread_count ?? 0;
  const notifications = data?.notifications ?? [];

  useEffect(() => {
    function handleClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setIsOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleOpenNotification = (note) => {
    if (!note.is_read) markRead(note.id);
    setIsOpen(false);
    if (note.link) navigate(note.link);
  };

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="glass relative rounded-xl p-2.5 text-white/70 transition-colors hover:text-white"
        aria-haspopup="menu"
        aria-expanded={isOpen}
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-secondary px-1 text-[10px] font-semibold text-white">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="fixed inset-x-4 top-20 z-30 mt-0 origin-top animate-scale-in overflow-hidden rounded-2xl border border-white/10 bg-primary-900/95 p-2 shadow-2xl backdrop-blur-xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-auto sm:mt-2 sm:w-80">
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="text-sm font-medium text-white">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={() => markAllRead()}
                className="flex items-center gap-1 text-xs text-secondary hover:underline"
              >
                <CheckCheck className="h-3.5 w-3.5" /> Mark all read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {isLoading ? (
              <p className="px-2 py-4 text-center text-sm text-white/40">Loading…</p>
            ) : notifications.length === 0 ? (
              <p className="px-2 py-4 text-center text-sm text-white/40">No notifications yet.</p>
            ) : (
              notifications.map((note) => (
                <button
                  key={note.id}
                  onClick={() => handleOpenNotification(note)}
                  className={clsx(
                    "block w-full rounded-lg px-2 py-2 text-left transition-colors hover:bg-white/10",
                    !note.is_read && "bg-white/5"
                  )}
                >
                  <div className="flex items-start gap-2">
                    {!note.is_read && <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-secondary" />}
                    <div className={clsx("min-w-0 flex-1", note.is_read && "pl-3.5")}>
                      <p className="truncate text-sm text-white/90">{note.title}</p>
                      <p className="line-clamp-2 text-xs text-white/50">{note.body}</p>
                      <p className="mt-0.5 text-[11px] text-white/30">{formatDateTime(note.created_at)}</p>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>

          {notificationsPath && (
            <button
              onClick={() => {
                setIsOpen(false);
                navigate(notificationsPath);
              }}
              className="mt-1 block w-full rounded-lg px-2 py-2 text-center text-xs text-secondary hover:underline"
            >
              View all notifications
            </button>
          )}
        </div>
      )}
    </div>
  );
}
