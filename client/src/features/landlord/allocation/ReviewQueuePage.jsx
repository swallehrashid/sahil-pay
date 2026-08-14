import { useEffect, useState } from "react";
import { AlertCircle, Check, Undo2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import Badge from "@/components/ui/Badge";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import {
  useGetReviewQueueQuery,
  useAllocatePaymentMutation,
  useReversePaymentMutation,
} from "./allocationApiSlice";

// sahilpay_payment_allocation_spec.md §4.7 — the suspense / review queue.
//
// Money that arrived but could not be attributed with certainty. The most
// common case by far is a tenant renting several units who pays one lump sum
// quoting their phone: we know WHO paid, not WHICH unit, so the payment waits
// here with an arrears-first suggestion the manager can accept in one tap or
// adjust.
//
// This screen is unapologetically a to-do list — unlike the eTIMS Register,
// which deliberately isn't. The difference is real: an unallocated payment is
// money in the paybill that hasn't reached a landlord, and that IS urgent.
//
// Mobile-first: every payment is a card, and the split editor is a stacked
// column of amount inputs, because this gets cleared on a phone between
// viewings.

const REASON_COPY = {
  multi_lease: "Pays for more than one unit",
  unknown_reference: "Couldn't be matched to a tenant",
  code_no_active_lease: "Unit code has no active tenant",
  ambiguous_phone: "Couldn't be narrowed to one tenant",
  no_source_match: "Arrived through an unrecognised paybill",
  reversal_pending: "Reversed at M-Pesa",
};

function SplitEditor({ payment, onClose }) {
  const [allocate, { isLoading }] = useAllocatePaymentMutation();
  const [rows, setRows] = useState([]);

  useEffect(() => {
    // Seed from the server's arrears-first suggestion. It is a starting point,
    // never a commitment — the manager edits freely before saving.
    setRows((payment.suggested_split ?? []).map((row) => ({
      tenant_id: row.tenant_id,
      unit_name: row.unit_name,
      amount: row.amount,
    })));
  }, [payment]);

  const total = rows.reduce((sum, r) => sum + Number(r.amount || 0), 0);
  const paymentAmount = Number(payment.amount || 0);
  const over = total > paymentAmount + 0.005;
  const remaining = paymentAmount - total;

  const save = async () => {
    try {
      await allocate({
        paymentId: payment.id,
        splits: rows
          .filter((r) => Number(r.amount) > 0)
          .map((r) => ({ tenant_id: r.tenant_id, amount: r.amount })),
      }).unwrap();
      toast("Allocated.", { type: "success" });
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not allocate that payment.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`Allocate ${payment.payment_ref}`} size="lg">
      <div className="space-y-4">
        <div className="glass p-4 text-sm">
          <div className="flex flex-col gap-1 sm:flex-row sm:justify-between">
            <span className="text-white/50">Amount received</span>
            <span className="font-medium text-white">{formatCurrency(payment.amount)}</span>
          </div>
          <div className="mt-1 flex flex-col gap-1 sm:flex-row sm:justify-between">
            <span className="text-white/50">Still to allocate</span>
            <span className={over ? "font-medium text-secondary" : "font-medium text-white/80"}>
              {formatCurrency(remaining)}
            </span>
          </div>
        </div>

        {!rows.length ? (
          <p className="text-sm text-white/50">
            No suggestion available for this payment — it could not be matched to a
            tenant at all. Record it manually from the Payments page instead.
          </p>
        ) : (
          <div className="space-y-3">
            {rows.map((row, index) => (
              <div key={row.tenant_id}
                   className="flex flex-col gap-2 rounded-lg border border-white/10 p-3 sm:flex-row sm:items-end">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-white">
                    {row.unit_name || `Tenant #${row.tenant_id}`}
                  </div>
                </div>
                <Input
                  label="Amount"
                  type="number"
                  value={row.amount}
                  className="sm:max-w-[10rem]"
                  onChange={(e) =>
                    setRows((prev) => prev.map((r, i) =>
                      i === index ? { ...r, amount: e.target.value } : r))
                  }
                />
              </div>
            ))}
          </div>
        )}

        {over && (
          <p className="text-sm text-secondary">
            That splits more than the payment. Reduce one of the amounts.
          </p>
        )}

        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="button" onClick={save} isLoading={isLoading}
                  disabled={over || !rows.some((r) => Number(r.amount) > 0)}>
            <Check size={14} className="mr-1" /> Confirm allocation
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function ReviewQueuePage() {
  const { data, isLoading } = useGetReviewQueueQuery();
  const [reverse] = useReversePaymentMutation();
  const [active, setActive] = useState(null);

  if (isLoading) return <SkeletonForm fields={6} />;

  const payments = data?.payments ?? [];
  const unparsed = data?.unparsed_messages ?? [];

  const handleReverse = async (payment) => {
    try {
      await reverse({ paymentId: payment.id, reason: "Reversed from review queue" }).unwrap();
      toast("Payment reversed.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not reverse that payment.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payments to review"
        subtitle="Money that arrived but hasn't been matched to a unit yet. Nothing is allocated until you confirm it."
      />

      {!payments.length && !unparsed.length ? (
        <EmptyState
          title="Nothing waiting"
          description="Every payment received has been matched and allocated."
        />
      ) : (
        <>
          {payments.map((payment) => (
            <div key={payment.id} className="glass space-y-3 p-5 sm:p-6">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-medium text-white">
                      {formatCurrency(payment.amount)}
                    </span>
                    <Badge color="amber">
                      {REASON_COPY[payment.suspense_reason] ?? "Needs review"}
                    </Badge>
                  </div>
                  <div className="mt-1 space-y-0.5 text-xs text-white/40">
                    <div>{payment.payment_ref} · {payment.payment_date}</div>
                    {payment.reference_text && <div>Reference: {payment.reference_text}</div>}
                    {payment.tenant_name && <div>{payment.tenant_name}</div>}
                  </div>
                </div>

                <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
                  <Button type="button" variant="ghost" onClick={() => handleReverse(payment)}>
                    <Undo2 size={14} className="mr-1" /> Reverse
                  </Button>
                  <Button type="button" onClick={() => setActive(payment)}>
                    Allocate
                  </Button>
                </div>
              </div>

              {payment.suggested_split?.length > 0 && (
                <div className="border-t border-white/10 pt-3 text-xs text-white/50">
                  Suggested (arrears first):{" "}
                  {payment.suggested_split
                    .map((s) => `${s.unit_name ?? "unit"} ${formatCurrency(s.amount)}`)
                    .join(" · ")}
                </div>
              )}
            </div>
          ))}

          {unparsed.length > 0 && (
            <div className="glass space-y-3 p-5 sm:p-6">
              <div className="flex items-center gap-2">
                <AlertCircle size={16} className="shrink-0 text-white/40" />
                <h3 className="text-sm font-medium text-white">
                  Messages we couldn&apos;t read ({unparsed.length})
                </h3>
              </div>
              <p className="text-xs text-white/40">
                Forwarded SMS that matched no known format. The full text is kept —
                nothing is discarded — so support can add a template for it.
              </p>
              <div className="space-y-2">
                {unparsed.slice(0, 10).map((message) => (
                  <div key={message.id}
                       className="rounded border border-white/10 p-2 text-xs text-white/60">
                    <div className="text-white/40">
                      {message.sender_id} · {message.created_at?.slice(0, 10)}
                    </div>
                    <div className="mt-1 break-words">{message.raw_text}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {active && <SplitEditor payment={active} onClose={() => setActive(null)} />}
    </div>
  );
}
