import { ShieldAlert } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";

// Shown when an admin is impersonating this account (§10.5) — never a silent backdoor.
export default function ImpersonationBanner() {
  const { impersonating } = useAuth();
  if (!impersonating) return null;

  return (
    <div className="mb-6 flex items-center gap-3 rounded-2xl border border-secondary/40 bg-secondary/15 px-4 py-3 text-sm text-secondary-100 animate-fade-in-up">
      <ShieldAlert className="h-4 w-4 flex-shrink-0" />
      A Sahil Pay admin is currently assisting your account in a client support session.
    </div>
  );
}
