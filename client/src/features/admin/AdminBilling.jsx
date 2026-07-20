import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import Tabs from "@/components/ui/Tabs";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import { toast } from "@/components/ui/Toast";
import Pagination from "@/components/ui/Pagination";
import { usePagination } from "@/hooks/usePagination";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";
import {
  useGetAdminBillingTransactionsQuery, useVerifyBillingTransactionMutation,
  useReverseBillingTransactionMutation, useGetAdminC2bPaymentsQuery,
  useResolveC2bPaymentMutation,
} from "./adminBillingApiSlice";

const SECTIONS = [
  { key: "transactions", label: "Transactions" },
  { key: "paybill", label: "Paybill payments" },
];

export default function AdminBilling() {
  const [section, setSection] = useState("transactions");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Billing"
        subtitle="Platform subscription/SMS payments and direct-paybill reconciliation"
        breadcrumbs={[{ label: "Admin", to: ADMIN_ROUTES.dashboard }, { label: "Billing" }]}
      />
      <Tabs tabs={SECTIONS} activeKey={section} onChange={setSection} />
      {section === "transactions" ? <TransactionsSection /> : <PaybillSection />}
    </div>
  );
}

function TransactionsSection() {
  const [verifiedFilter, setVerifiedFilter] = useState("");
  const { page, perPage, setPage, setPerPage, params } = usePagination(25);
  const { data, isLoading } = useGetAdminBillingTransactionsQuery({
    ...params, ...(verifiedFilter ? { is_verified: verifiedFilter } : {}),
  });
  const [verify, { isLoading: isVerifying }] = useVerifyBillingTransactionMutation();
  const [reverseModal, setReverseModal] = useState(null);

  const handleVerify = async (txn) => {
    try {
      await verify(txn.id).unwrap();
      toast("Transaction verified.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not verify transaction.", { type: "error" });
    }
  };

  const columns = [
    { key: "created_at", header: "Date", render: (r) => formatDate(r.created_at) },
    { key: "landlord_name", header: "Landlord" },
    { key: "type", header: "Type" },
    { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount) },
    { key: "payment_reference", header: "Reference", render: (r) => r.payment_reference ?? "—" },
    {
      key: "status",
      header: "Status",
      render: (r) => (
        <div className="flex items-center gap-2">
          <StatusBadge status={r.status} />
          {r.is_verified ? <span className="text-xs text-emerald-400">Verified</span> : null}
          {r.is_reversed ? <span className="text-xs text-rose-400">Reversed</span> : null}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <Select
        value={verifiedFilter}
        onChange={(e) => { setVerifiedFilter(e.target.value); setPage(1); }}
        options={[
          { value: "", label: "All" },
          { value: "false", label: "Unverified only" },
          { value: "true", label: "Verified only" },
        ]}
        className="max-w-xs"
      />
      <div className="glass p-6">
        <ResponsiveTable
          columns={columns}
          rows={data?.transactions ?? []}
          isLoading={isLoading}
          emptyState={<div className="py-10 text-center text-sm text-white/50">No billing transactions.</div>}
          rowActions={(r) => (
            <div className="flex justify-end gap-2">
              {!r.is_verified && (
                <Button size="sm" isLoading={isVerifying} onClick={() => handleVerify(r)}>Verify</Button>
              )}
              {r.is_verified && !r.is_reversed && (
                <Button size="sm" variant="danger" onClick={() => setReverseModal(r)}>Reverse</Button>
              )}
            </div>
          )}
        />
        <Pagination page={page} perPage={perPage} total={data?.total ?? 0} onPageChange={setPage} onPerPageChange={setPerPage} />
      </div>
      <ReverseModal txn={reverseModal} onClose={() => setReverseModal(null)} />
    </div>
  );
}

function ReverseModal({ txn, onClose }) {
  const [reason, setReason] = useState("");
  const [reverse, { isLoading }] = useReverseBillingTransactionMutation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!reason.trim()) {
      toast("Enter a reason.", { type: "error" });
      return;
    }
    try {
      await reverse({ id: txn.id, reason }).unwrap();
      toast("Transaction reversed.", { type: "success" });
      setReason("");
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not reverse transaction.", { type: "error" });
    }
  };

  return (
    <Modal
      isOpen={Boolean(txn)}
      onClose={onClose}
      title="Reverse transaction"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" onClick={handleSubmit} isLoading={isLoading}>Reverse</Button>
        </>
      }
    >
      {txn && (
        <div className="space-y-4">
          <p className="text-sm text-white/60">
            Reversing KES {formatCurrency(txn.amount)} claws back any affiliate commission tied to this
            transaction. The landlord keeps the service period already granted.
          </p>
          <Input label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} required />
        </div>
      )}
    </Modal>
  );
}

function PaybillSection() {
  const [statusFilter, setStatusFilter] = useState("unmatched");
  const { page, perPage, setPage, setPerPage, params } = usePagination(25);
  const { data, isLoading } = useGetAdminC2bPaymentsQuery({
    ...params, ...(statusFilter ? { status: statusFilter } : {}),
  });
  const [resolveModal, setResolveModal] = useState(null);

  const columns = [
    { key: "created_at", header: "Received", render: (r) => formatDate(r.created_at) },
    { key: "trans_id", header: "M-Pesa receipt" },
    { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount) },
    { key: "bill_ref", header: "Account ref", render: (r) => r.bill_ref || "—" },
    { key: "payer_name", header: "Payer", render: (r) => r.payer_name || "—" },
    { key: "landlord_name", header: "Landlord", render: (r) => r.landlord_name || "—" },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
  ];

  return (
    <div className="space-y-4">
      <Select
        value={statusFilter}
        onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
        options={[
          { value: "unmatched", label: `Unmatched${data?.unmatched_count ? ` (${data.unmatched_count})` : ""}` },
          { value: "matched", label: "Matched" },
          { value: "resolved", label: "Resolved" },
          { value: "", label: "All" },
        ]}
        className="max-w-xs"
      />
      <div className="glass p-6">
        <ResponsiveTable
          columns={columns}
          rows={data?.payments ?? []}
          isLoading={isLoading}
          emptyState={<div className="py-10 text-center text-sm text-white/50">No paybill payments in this state.</div>}
          rowActions={(r) => (
            r.status === "unmatched" && (
              <Button size="sm" onClick={() => setResolveModal(r)}>Resolve</Button>
            )
          )}
        />
        <Pagination page={page} perPage={perPage} total={data?.total ?? 0} onPageChange={setPage} onPerPageChange={setPerPage} />
      </div>
      <ResolveModal payment={resolveModal} onClose={() => setResolveModal(null)} />
    </div>
  );
}

function ResolveModal({ payment, onClose }) {
  const [landlordId, setLandlordId] = useState("");
  const [applyAs, setApplyAs] = useState("subscription");
  const [note, setNote] = useState("");
  const [resolve, { isLoading }] = useResolveC2bPaymentMutation();

  const reset = () => { setLandlordId(""); setApplyAs("subscription"); setNote(""); };
  const close = () => { reset(); onClose(); };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (applyAs !== "ignore" && !landlordId.trim()) {
      toast("Enter the landlord ID.", { type: "error" });
      return;
    }
    try {
      await resolve({
        id: payment.id,
        apply_as: applyAs,
        ...(applyAs !== "ignore" ? { landlord_id: Number(landlordId) } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      }).unwrap();
      toast("Payment resolved.", { type: "success" });
      close();
    } catch (err) {
      toast(err?.data?.error || "Could not resolve payment.", { type: "error" });
    }
  };

  return (
    <Modal
      isOpen={Boolean(payment)}
      onClose={close}
      title="Resolve paybill payment"
      footer={
        <>
          <Button variant="ghost" onClick={close}>Cancel</Button>
          <Button onClick={handleSubmit} isLoading={isLoading}>Resolve</Button>
        </>
      }
    >
      {payment && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-sm">
            <div className="flex justify-between py-1"><span className="text-white/50">Receipt</span><span className="font-mono text-white">{payment.trans_id}</span></div>
            <div className="flex justify-between py-1"><span className="text-white/50">Amount</span><span className="text-white">{formatCurrency(payment.amount)}</span></div>
            <div className="flex justify-between py-1"><span className="text-white/50">Account ref</span><span className="text-white">{payment.bill_ref || "—"}</span></div>
          </div>
          <Select
            label="Apply as"
            value={applyAs}
            onChange={(e) => setApplyAs(e.target.value)}
            options={[
              { value: "subscription", label: "Subscription payment" },
              { value: "sms", label: "SMS credit purchase" },
              { value: "ignore", label: "Ignore (no financial effect)" },
            ]}
          />
          {applyAs !== "ignore" && (
            <Input
              label="Landlord ID"
              type="number"
              value={landlordId}
              onChange={(e) => setLandlordId(e.target.value)}
              hint="The landlord this payment belongs to"
              required
            />
          )}
          <Input label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        </form>
      )}
    </Modal>
  );
}
