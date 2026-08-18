import { Clock, Trash2 } from "lucide-react";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import EmptyState from "@/components/ui/EmptyState";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { usePermissions } from "@/hooks/usePermissions";
import {
  useGetInvoiceQueueQuery,
  useApplyQueuedChargesMutation,
  useCancelQueuedChargeMutation,
} from "./invoiceQueueApiSlice";

/**
 * What is waiting to be billed.
 *
 * A queued charge is invisible by design at the moment it is created — that is
 * the point, it is being held. But invisible-forever is how a caretaker's
 * reading quietly never reaches a bill, so the queue needs a screen of its own
 * where somebody can see the total sitting there, bill it early, or throw out a
 * misread meter.
 *
 * Grouped by unit because that is what a queued charge is attached to: the
 * water was used by the meter, not by whoever happens to live there in April.
 */
export default function InvoiceQueuePanel() {
  const { can } = usePermissions();
  const canBill = can("invoices", "edit");

  const { data, isLoading } = useGetInvoiceQueueQuery();
  const [applyQueued, { isLoading: applying }] = useApplyQueuedChargesMutation();
  const [cancelCharge] = useCancelQueuedChargeMutation();

  const charges = data?.charges ?? [];
  const units = data?.units ?? [];

  const byUnit = units.map((u) => ({
    ...u,
    charges: charges.filter((c) => c.unit_id === u.unit_id),
  }));

  const applyNow = async (unitId) => {
    try {
      const result = await applyQueued({ unitId }).unwrap();
      toast(`Added to ${result.invoice_number}.`, { type: "success" });
    } catch (err) {
      // The common refusal is "no open invoice" — say what to do instead
      // rather than reporting a failure the person cannot act on.
      toast(err?.data?.message || "Could not apply these charges.", { type: "error" });
    }
  };

  const drop = async (id) => {
    try {
      await cancelCharge(id).unwrap();
      toast("Charge cancelled — it will not be billed.", { type: "info" });
    } catch {
      toast("Could not cancel that charge.", { type: "error" });
    }
  };

  if (isLoading) return null;

  if (charges.length === 0) {
    return (
      <EmptyState
        title="Nothing waiting"
        description="Meter readings held for a later invoice will appear here."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="glass flex flex-wrap items-center justify-between gap-3 p-4">
        <p className="flex items-center gap-2 text-sm text-white/70">
          <Clock className="h-4 w-4" />
          {data.count} charge{data.count === 1 ? "" : "s"} waiting across{" "}
          {units.length} unit{units.length === 1 ? "" : "s"}
        </p>
        <p className="text-lg font-light text-white">{formatCurrency(data.total)}</p>
      </div>

      <p className="text-xs leading-relaxed text-white/40">
        These are folded into each unit's next monthly invoice automatically. Bill
        one early only if you need it on an invoice that is already open.
      </p>

      {byUnit.map((unit) => (
        <div key={unit.unit_id} className="glass p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-white/85">{unit.unit_name}</p>
              <p className="text-xs text-white/40">
                {unit.count} charge{unit.count === 1 ? "" : "s"} · {formatCurrency(unit.total)}
              </p>
            </div>
            {canBill && (
              <Button variant="ghost" onClick={() => applyNow(unit.unit_id)}
                      isLoading={applying}>
                Bill now
              </Button>
            )}
          </div>

          <ul className="space-y-2">
            {unit.charges.map((c) => (
              <li key={c.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white/5 px-3 py-2">
                <div className="min-w-0">
                  <p className="text-sm text-white/85">
                    {c.item}
                    <span className="ml-2 text-white/50">{formatCurrency(c.amount)}</span>
                  </p>
                  <p className="text-xs text-white/40">
                    {c.description || "—"} · held {formatDate(c.created_at)}
                    {/* Who was in the unit when it was queued. A different name
                        here means the tenant changed between the reading and
                        the bill, which somebody needs to notice BEFORE it is
                        billed to the wrong person. */}
                    {c.occupant_at_queue && ` · read against ${c.occupant_at_queue}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge color="white">waiting</Badge>
                  {canBill && (
                    <button
                      onClick={() => drop(c.id)}
                      aria-label={`Cancel ${c.item}`}
                      className="text-white/30 transition-colors hover:text-secondary"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
