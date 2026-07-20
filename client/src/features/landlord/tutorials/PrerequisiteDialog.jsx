import ConfirmDialog from "@/components/ui/ConfirmDialog";

// Shown when starting a tutorial whose prerequisite data doesn't exist yet — e.g. "Add units"
// with zero properties (§10.3).
export default function PrerequisiteDialog({ prerequisiteTitle, onStart, onCancel }) {
  return (
    <ConfirmDialog
      isOpen
      onClose={onCancel}
      onConfirm={onStart}
      title="One thing first"
      description={`You'll need to run "${prerequisiteTitle}" first — start it now?`}
      confirmLabel="Start it"
      cancelLabel="Cancel"
      isDangerous={false}
    />
  );
}
