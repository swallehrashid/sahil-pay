import { Bell } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";

export default function AdminNavbar() {
  const { user } = useAuth();
  return (
    <div className="hidden items-center justify-end gap-4 px-4 pt-4 lg:flex">
      <button className="glass rounded-xl p-2.5 text-white/70 transition-colors hover:text-white">
        <Bell className="h-4 w-4" />
      </button>
      <div className="glass flex items-center gap-2 rounded-xl px-3 py-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-third text-xs font-medium text-white">
          {(user?.first_name || "A")[0].toUpperCase()}
        </span>
        <span className="text-sm text-white/80">{user?.email}</span>
      </div>
    </div>
  );
}
