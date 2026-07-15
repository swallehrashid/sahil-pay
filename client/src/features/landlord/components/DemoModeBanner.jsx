import { useState } from "react";
import { FlaskConical, LogOut, RotateCcw } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { USER_ROLES } from "@/utils/constants";
import { useDemoMode } from "@/features/landlord/useDemoMode";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

// Persistent, non-dismissible reminder shown across every landlord-portal
// page while browsing the demo shadow account (DEMO_MODE_SPEC.md §5.4).
// Deliberately has NO close/dismiss affordance — only "Exit demo" ends it.
export default function DemoModeBanner() {
  const { role } = useAuth();
  const { isActive, exit, reset, isExiting, isResetting } = useDemoMode();
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const isLandlordRole = role === USER_ROLES.LANDLORD || role === USER_ROLES.PROPERTY_MANAGER;
  if (!isActive || !isLandlordRole) return null;

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-400/40 bg-amber-400/15 px-4 py-3 text-sm text-amber-100 animate-fade-in-up">
        <div className="flex items-center gap-3">
          <FlaskConical className="h-4 w-4 flex-shrink-0" />
          <span>
            <strong>Demo mode</strong> — you&apos;re practicing with example data. Nothing you do here is saved to your real account.
          </span>
        </div>
        <div className="flex items-center gap-4 whitespace-nowrap">
          <button
            onClick={() => setShowResetConfirm(true)}
            className="flex items-center gap-1 text-amber-100 hover:underline"
            disabled={isResetting}
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset demo data
          </button>
          <button onClick={exit} className="flex items-center gap-1 text-amber-100 hover:underline" disabled={isExiting}>
            <LogOut className="h-3.5 w-3.5" /> Exit demo
          </button>
        </div>
      </div>

      <ConfirmDialog
        isOpen={showResetConfirm}
        onClose={() => setShowResetConfirm(false)}
        onConfirm={async () => {
          await reset();
          setShowResetConfirm(false);
        }}
        title="Reset demo data?"
        description="This wipes any practice changes you've made in demo mode and restores the original example data. Your real account is never affected."
        confirmLabel="Reset demo data"
        isDangerous={false}
        isLoading={isResetting}
      />
    </>
  );
}
