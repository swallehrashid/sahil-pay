import { useState } from "react";
import { Check, PartyPopper, X } from "lucide-react";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useAuth } from "@/hooks/useAuth";
import { useOnboardingState } from "./useOnboardingState";
import { useTour } from "./TourProvider";
import { ANCHORS } from "./anchors";

// Dashboard checklist card — the durable fallback for landlords who skip the welcome modal
// (ONBOARDING_TUTORIALS_SPEC.md §6.3). Items auto-complete from real data OR from a
// completed/skipped tutorial, whichever happens first.
const ITEMS = [
  { key: "properties", label: "Create your first property", tutorialId: "create-property", countKey: "properties" },
  { key: "units", label: "Add your units", tutorialId: "add-units", countKey: "units" },
  { key: "tenants", label: "Add a tenant", tutorialId: "add-tenant", countKey: "tenants" },
  { key: "categories", label: "Set up your charge categories", tutorialId: "charge-categories", countKey: "charge_categories" },
  { key: "invoices", label: "Create your first invoice", tutorialId: "create-invoice", countKey: "invoices" },
  { key: "payments", label: "Record a payment", tutorialId: "record-payment", countKey: "payments" },
  { key: "communications", label: "Learn how tenant messaging works", tutorialId: "communications", countKey: null },
  { key: "reports", label: "See your reports", tutorialId: "reports", countKey: null },
];

export default function GettingStartedChecklist() {
  const { role, impersonating } = useAuth();
  const onboarding = useOnboardingState();
  const { startTutorial } = useTour();
  const [confirmDismiss, setConfirmDismiss] = useState(false);

  const isEligible = (role === "landlord" || role === "property_manager") && !impersonating;
  if (!isEligible || !onboarding.isHydrated) return null;
  if (onboarding.state?.checklist_dismissed_at) return null;

  const isDone = (item) => {
    if (item.countKey && (onboarding.counts[item.countKey] ?? 0) > 0) return true;
    const status = onboarding.tutorialStatus(item.tutorialId);
    return item.countKey ? status === "completed" : status === "completed" || status === "skipped";
  };

  const doneCount = ITEMS.filter(isDone).length;
  const allDone = doneCount === ITEMS.length;

  return (
    <div data-tour={ANCHORS.dashboard.checklist} className="glass mb-6 animate-fade-in-up p-5">
      {allDone ? (
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
              <PartyPopper className="h-5 w-5" />
            </span>
            <p className="text-sm text-white/80">You're all set — every basic is covered.</p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => onboarding.dismissChecklist()}>
            Hide this
          </Button>
        </div>
      ) : (
        <>
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium text-white">Getting started</h3>
              <p className="text-xs text-white/40">{doneCount} of {ITEMS.length} done</p>
            </div>
            <button
              type="button"
              onClick={() => setConfirmDismiss(true)}
              className="rounded-lg p-1 text-white/40 transition-colors hover:bg-white/10 hover:text-white"
              aria-label="Dismiss checklist"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-secondary transition-all duration-300"
              style={{ width: `${(doneCount / ITEMS.length) * 100}%` }}
            />
          </div>
          <ul className="space-y-2">
            {ITEMS.map((item) => {
              const done = isDone(item);
              return (
                <li key={item.key} className="flex items-center justify-between gap-3 text-sm">
                  <span className="flex items-center gap-2">
                    <span
                      className={
                        "flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full " +
                        (done ? "bg-emerald-500/20 text-emerald-300" : "bg-white/10 text-white/30")
                      }
                    >
                      <Check className="h-3 w-3" />
                    </span>
                    <span className={done ? "text-white/40 line-through" : "text-white/80"}>{item.label}</span>
                  </span>
                  {!done && (
                    <Button variant="subtle" size="sm" onClick={() => startTutorial(item.tutorialId, { origin: "standalone" })}>
                      Show me
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}

      <ConfirmDialog
        isOpen={confirmDismiss}
        onClose={() => setConfirmDismiss(false)}
        onConfirm={() => {
          onboarding.dismissChecklist();
          setConfirmDismiss(false);
        }}
        title="Dismiss the getting-started checklist?"
        description="You can still run any tutorial later from Help & Tutorials in the sidebar."
        confirmLabel="Dismiss"
        isDangerous={false}
      />
    </div>
  );
}
