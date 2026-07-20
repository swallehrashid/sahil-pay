import { ShieldOff } from "lucide-react";
import Button from "@/components/ui/Button";
import { useDemoMode } from "@/features/landlord/useDemoMode";

// Interstitial shown in place of an account-level settings page while in demo
// mode (DEMO_MODE_SPEC.md §5.6) — a belt-and-braces guard for direct
// navigation, since the nav itself already hides these items in demo.
export default function DemoBlockedPage() {
  const { exit, isExiting } = useDemoMode();

  return (
    <div className="glass flex flex-col items-center gap-4 p-12 text-center">
      <ShieldOff className="h-8 w-8 text-white/40" />
      <div>
        <h3 className="text-base font-medium text-white">Unavailable in demo mode</h3>
        <p className="mt-1 text-sm text-white/50">
          This page manages your real account and is unavailable while you&apos;re in demo mode.
        </p>
      </div>
      <Button type="button" variant="subtle" size="sm" onClick={exit} isLoading={isExiting}>
        Exit demo mode
      </Button>
    </div>
  );
}
