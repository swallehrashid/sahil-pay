import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import { CheckCircle2 } from "lucide-react";

// Centered card shown between two tutorials in the onboarding sequence (§7.0).
export default function SequenceInterstitial({ finishedTitle, nextTitle, nextDuration, onContinue, onFinishLater }) {
  return (
    <Modal isOpen onClose={onFinishLater} size="sm">
      <div className="space-y-4 text-center">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
          <CheckCircle2 className="h-6 w-6" />
        </span>
        <div>
          <p className="text-sm text-white/60">
            Nice — <span className="text-white">{finishedTitle}</span> done.
          </p>
          <p className="mt-2 text-sm text-white/70">
            Next up: <span className="font-medium text-white">{nextTitle}</span>{" "}
            <span className="text-white/40">({nextDuration})</span>
          </p>
        </div>
        <div className="flex flex-col gap-2 pt-1">
          <Button onClick={onContinue}>Continue</Button>
          <Button variant="ghost" onClick={onFinishLater}>
            Finish later
          </Button>
        </div>
      </div>
    </Modal>
  );
}
