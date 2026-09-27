import { useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { CalendarClock, CheckCheck, Clock, Trash2, X } from "lucide-react";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Checkbox from "@/components/ui/Checkbox";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import EmptyState from "@/components/ui/EmptyState";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { usePermissions } from "@/hooks/usePermissions";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";
import {
  useGetInvoiceQueueQuery,
  useApplyQueuedChargesMutation,
  useCancelQueuedChargeMutation,
  useReviewQueuedChargesMutation,
  useRunMonthlyInvoicingMutation,
} from "./invoiceQueueApiSlice";

/**
 * Charges held for a unit's next invoice, in two stages.
 *
 *   Waiting for review  — submitted by someone who cannot bill (a caretaker
 *                         entering meter readings). Nothing invoices these
 *                         until an invoices editor approves them.
 *   Approved            — go onto the unit's next monthly invoice together with
 *                         rent and any unpaid balance carried forward.
 *
 * Grouped by unit because that is what a queued charge is attached to: the
 * water was used by the meter, not by whoever happens to live there in April.
 */
export default function InvoiceQueuePanel() {
  const { can } = usePermissions();
  const canBill = can("invoices", "edit");
  const { pathname } = useLocation();
  const isOwner = pathname.startsWith("/landlord");

  const { data, isLoading } = useGetInvoiceQueueQuery();
  const { data: pendingData } = useGetInvoiceQueueQuery({ status: "pending" });
  const [applyQueued, { isLoading: applying }] = useApplyQueuedChargesMutation();
  const [cancelCharge] = useCancelQueuedChargeMutation();
  const [review, { isLoading: reviewing }] = useReviewQueuedChargesMutation();
  const [isRunOpen, setIsRunOpen] = useState(false);

  const charges = data?.charges ?? [];
  const units = data?.units ?? [];
  const pending = pendingData?.charges ?? [];
  const automation = data?.automation;

  const byUnit = units.map((u) => ({
    ...u,
    charges: charges.filter((c) => c.unit_id === u.unit_id),
  }));

  const applyNow = async (unitId) => {
    try {
      const result = await applyQueued({ unitId }).unwrap();
      toast(`Added to ${result.invoice_number}.`, { type: "success" });
    } catch (err) {
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

  const doReview = async (body) => {
    try {
      const res = await review(body).unwrap();
      toast(res.message || "Done.", { type: "success" });
      return true;
    } catch (err) {
      toast(err?.data?.message || err?.data?.error || "Could not update those charges.", { type: "error" });
      return false;
    }
  };

  if (isLoading) return null;

  return (
    <div className="space-y-6">
      <AutomationStrip automation={automation} isOwner={isOwner} canBill={canBill}
                       onRunNow={() => setIsRunOpen(true)} />

      <ReviewSection pending={pending} canBill={canBill} reviewing={reviewing} onReview={doReview} />

      <section className="space-y-4" data-testid="approved-queue" data-tour={ANCHORS.invoices.approvedSection}>
        <h2 className="text-sm font-medium uppercase tracking-wide text-white/40">
          Approved — goes on the next invoice
        </h2>
        {charges.length === 0 ? (
          <EmptyState
            title="Nothing approved yet"
            description="Approved meter readings and other queued charges appear here until an invoice takes them."
          />
        ) : (
          <>
            <div className="glass flex flex-wrap items-center justify-between gap-3 p-4">
              <p className="flex items-center gap-2 text-sm text-white/70">
                <Clock className="h-4 w-4" />
                {data.count} charge{data.count === 1 ? "" : "s"} approved across{" "}
                {units.length} unit{units.length === 1 ? "" : "s"}
              </p>
              <p className="text-lg font-light text-white">{formatCurrency(data.total)}</p>
            </div>

            {byUnit.map((unit) => (
              <div key={unit.unit_id} className="glass p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-white/85">
                      {unit.unit_name}
                      {unit.charges[0]?.property_name && (
                        <span className="text-white/40"> · {unit.charges[0].property_name}</span>
                      )}
                    </p>
                    <p className="text-xs text-white/40">
                      {unit.count} charge{unit.count === 1 ? "" : "s"} · {formatCurrency(unit.total)}
                    </p>
                  </div>
                  {canBill && (
                    <Button variant="ghost" onClick={() => applyNow(unit.unit_id)} isLoading={applying}>
                      Add to open invoice now
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
                          {c.occupant_at_queue && ` · read against ${c.occupant_at_queue}`}
                          {c.reviewed_by && ` · approved by ${c.reviewed_by}`}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge color="emerald">approved</Badge>
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
          </>
        )}
      </section>

      <RunMonthlyModal isOpen={isRunOpen} onClose={() => setIsRunOpen(false)} automation={automation} />
    </div>
  );
}

function AutomationStrip({ automation, isOwner, canBill, onRunNow }) {
  const on = (v) => (v ? "ON" : "OFF");
  return (
    <div className="glass flex flex-wrap items-center justify-between gap-3 p-4" data-testid="queue-automation">
      <div className="flex items-start gap-3">
        <CalendarClock className="mt-0.5 h-5 w-5 text-secondary" />
        <div className="text-sm">
          <p className="text-white/85">On the 1st of every month</p>
          <p className="text-xs text-white/50">
            Rent invoicing: <strong className="text-white/80">{on(automation?.auto_invoice_rent)}</strong> ·
            Approved queued charges: <strong className="text-white/80">{on(automation?.auto_invoice_queued)}</strong>
            {isOwner ? (
              <> — <Link className="underline hover:text-white" to={LANDLORD_ROUTES.settings.general}>change in Settings</Link></>
            ) : (
              <> — set by the account owner</>
            )}
          </p>
        </div>
      </div>
      {canBill && (
        <Button onClick={onRunNow} data-testid="run-monthly-open" data-tour={ANCHORS.invoices.runMonthly}>
          Create this month's invoices now
        </Button>
      )}
    </div>
  );
}

function ReviewSection({ pending, canBill, reviewing, onReview }) {
  const [selected, setSelected] = useState({});
  const ids = useMemo(() => pending.map((c) => c.id), [pending]);
  const chosen = ids.filter((id) => selected[id]);
  const total = pending.reduce((sum, c) => sum + Number(c.amount || 0), 0);
  const allOn = chosen.length > 0 && chosen.length === ids.length;

  const run = async (body) => {
    if (await onReview(body)) setSelected({});
  };

  return (
    <section className="space-y-3" data-testid="review-queue" data-tour={ANCHORS.invoices.reviewSection}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium uppercase tracking-wide text-white/40">Waiting for review</h2>
          <p className="text-xs text-white/40">
            Submitted by team members who cannot bill — nothing is invoiced until it is approved.
          </p>
        </div>
        {pending.length > 0 && (
          <p className="text-sm text-white/70">
            {pending.length} charge{pending.length === 1 ? "" : "s"} · {formatCurrency(total)}
          </p>
        )}
      </div>

      {pending.length === 0 ? (
        <p className="glass p-4 text-sm text-white/50">Nothing is waiting for review.</p>
      ) : (
        <div className="glass p-4">
          {canBill && (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Checkbox
                label={allOn ? "Clear selection" : "Select all"}
                checked={allOn}
                onChange={(e) => setSelected(e.target.checked ? Object.fromEntries(ids.map((id) => [id, true])) : {})}
              />
              <div className="ml-auto flex flex-wrap gap-2">
                <Button variant="ghost" leftIcon={<X className="h-4 w-4" />} disabled={!chosen.length}
                        isLoading={reviewing} onClick={() => run({ action: "reject", charge_ids: chosen })}>
                  Reject selected
                </Button>
                <Button variant="ghost" disabled={!chosen.length} isLoading={reviewing}
                        onClick={() => run({ action: "approve", charge_ids: chosen })}>
                  Approve selected ({chosen.length})
                </Button>
                <Button leftIcon={<CheckCheck className="h-4 w-4" />} isLoading={reviewing}
                        onClick={() => run({ action: "approve", all: true })} data-testid="approve-all">
                  Approve all {pending.length}
                </Button>
              </div>
            </div>
          )}
          <ul className="max-h-[28rem] space-y-2 overflow-y-auto">
            {pending.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-3 rounded-lg bg-white/5 px-3 py-2">
                {canBill && (
                  <Checkbox
                    aria-label={`Select ${c.item} for ${c.unit_name}`}
                    checked={Boolean(selected[c.id])}
                    onChange={(e) => setSelected((cur) => ({ ...cur, [c.id]: e.target.checked }))}
                  />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-white/85">
                    {c.unit_name} <span className="text-white/40">· {c.property_name}</span>
                    <span className="ml-2">{c.item}</span>
                    <span className="ml-2 text-white/60">{formatCurrency(c.amount)}</span>
                  </p>
                  <p className="text-xs text-white/40">
                    {c.description || "—"}
                    {c.submitted_by && ` · submitted by ${c.submitted_by}`} · {formatDate(c.created_at)}
                  </p>
                </div>
                <Badge color="white">waiting</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function RunMonthlyModal({ isOpen, onClose, automation }) {
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Africa/Nairobi" });
  const [includeRent, setIncludeRent] = useState(true);
  const [includeQueued, setIncludeQueued] = useState(true);
  const [issueDate, setIssueDate] = useState(today);
  const [runMonthly, { isLoading }] = useRunMonthlyInvoicingMutation();

  const submit = async () => {
    try {
      const res = await runMonthly({
        include_rent: includeRent, include_queued: includeQueued, issue_date: issueDate,
      }).unwrap();
      toast(res.message || "Monthly invoicing started.", { type: "success", duration: 8000 });
      onClose();
    } catch (err) {
      toast(err?.data?.message || err?.data?.error || "Could not create the invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Create this month's invoices">
      <div className="space-y-4">
        <p className="text-sm text-white/60">
          One invoice per tenant for the month of the date below. Any unpaid balance from earlier
          months is carried forward onto it. A tenant who already has this month's invoice gets the
          approved charges added to that invoice instead.
        </p>
        <Checkbox label="Rent (and other fixed monthly charges)" checked={includeRent}
                  onChange={(e) => setIncludeRent(e.target.checked)} />
        <Checkbox label="Approved queued charges (utilities etc.)" checked={includeQueued}
                  onChange={(e) => setIncludeQueued(e.target.checked)} />
        <Input label="Invoice date" type="date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
        {automation && (
          <p className="text-xs text-white/40">
            The automatic run on the 1st is {automation.auto_invoice_rent || automation.auto_invoice_queued ? "ON" : "OFF"} for
            this account. Running it now is safe: nobody is invoiced twice for the same month.
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} isLoading={isLoading} disabled={!includeRent && !includeQueued}
                  data-testid="run-monthly-submit">
            Create invoices
          </Button>
        </div>
      </div>
    </Modal>
  );
}
