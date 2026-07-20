import ConfirmDialog from "@/components/ui/ConfirmDialog";

// Shared confirm modal for entering demo mode (DEMO_MODE_SPEC.md §5.5) — used
// by both the sidebar toggle and the Settings → General card.
export default function DemoModeEnterDialog({ isOpen, onClose, onConfirm, isLoading }) {
  return (
    <ConfirmDialog
      isOpen={isOpen}
      onClose={onClose}
      onConfirm={onConfirm}
      title="Enter demo mode?"
      confirmLabel={isLoading ? "Preparing demo data…" : "Enter demo mode"}
      isDangerous={false}
      isLoading={isLoading}
    >
      <div className="space-y-2 text-sm text-white/60">
        <p>
          Demo mode fills your portal with realistic example data — properties, units, tenants,
          invoices, and payments — so you can practice before using your real account.
        </p>
        <p>Everything is fully interactive, but nothing you do in demo mode is saved to your real account.</p>
        <p>A banner will remind you that you&apos;re in demo mode, and you can exit at any time. Your practice data is kept until you reset it.</p>
      </div>
    </ConfirmDialog>
  );
}
