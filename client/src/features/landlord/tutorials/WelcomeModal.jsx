import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import { SahilPayMark } from "@/components/branding/SahilPayLogo";

// First-login welcome (ONBOARDING_TUTORIALS_SPEC.md §6.2). Existing landlords who predate
// this feature see the same modal once too — `isReturning` swaps the copy so it never reads
// as "welcome to your brand-new account" for someone who's been using Sahil Pay for months.
export default function WelcomeModal({ isOpen, isReturning, onStart, onSkip }) {
  return (
    <Modal isOpen={isOpen} onClose={onSkip} title={isReturning ? "Take a quick tour of Sahil Pay" : "Welcome to Sahil Pay 👋"} size="sm">
      <div className="space-y-5">
        <SahilPayMark className="h-8 w-8 text-secondary" />
        <p className="text-sm text-white/70">
          Let's get your first property set up. This guided tour walks you through everything you need to start
          collecting rent — properties, units, tenants, invoices, payments and messaging your tenants. It takes
          about 10 minutes and you can leave at any point.
        </p>
        <div className="flex flex-col gap-3">
          <Button onClick={onStart}>Start the guided setup</Button>
          <Button variant="ghost" onClick={onSkip}>
            Skip for now — I'll explore on my own
          </Button>
          <p className="text-center text-xs text-white/40">
            You can run any tutorial later from Help & Tutorials in the sidebar.
          </p>
        </div>
      </div>
    </Modal>
  );
}
