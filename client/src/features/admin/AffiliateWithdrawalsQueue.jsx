import { useState } from "react";
import { Download } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Tabs from "@/components/ui/Tabs";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import { toast } from "@/components/ui/Toast";
import Pagination from "@/components/ui/Pagination";
import { usePagination } from "@/hooks/usePagination";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { ADMIN_ROUTES } from "@/config/routePaths";
import {
  useGetAdminAffiliateWithdrawalsQuery, useProcessAffiliateWithdrawalMutation,
  usePayAffiliateWithdrawalMutation, useRejectAffiliateWithdrawalMutation,
} from "./adminAffiliateApiSlice";

const TABS = [
  { key: "", label: "All" },
  { key: "requested", label: "Requested" },
  { key: "processing", label: "Processing" },
  { key: "paid", label: "Paid" },
  { key: "rejected", label: "Rejected" },
];

export default function AffiliateWithdrawalsQueue() {
  const [status, setStatus] = useState("requested");
  const { page, perPage, setPage, setPerPage, params } = usePagination(25);
  const { data, isLoading } = useGetAdminAffiliateWithdrawalsQuery({ ...params, ...(status ? { status } : {}) });
  const [process] = useProcessAffiliateWithdrawalMutation();
  const [payModal, setPayModal] = useState(null);
  const [rejectModal, setRejectModal] = useState(null);

  const handleProcess = async (w) => {
    try {
      await process(w.id).unwrap();
      toast("Marked as processing.", { type: "success" });
    } catch {
      toast("Could not update withdrawal.", { type: "error" });
    }
  };

  const downloadReceipt = async (w) => {
    try {
      await downloadFile(`/admin/affiliates/withdrawals/${w.id}/receipt`, { filename: `${w.receipt_number}.pdf`, format: "pdf" });
    } catch {
      toast("Could not download receipt.", { type: "error" });
    }
  };

  const columns = [
    { key: "created_at", header: "Requested", render: (r) => formatDate(r.created_at) },
    { key: "affiliate_name", header: "Affiliate", render: (r) => r.affiliate_name },
    { key: "affiliate_mpesa_number", header: "M-Pesa", render: (r) => r.affiliate_mpesa_number ?? "—" },
    { key: "gross_amount", header: "Gross", render: (r) => formatCurrency(r.gross_amount) },
    { key: "net_amount", header: "Net", render: (r) => formatCurrency(r.net_amount) },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Withdrawal queue"
        subtitle="Process, pay, or reject affiliate withdrawal requests"
        breadcrumbs={[
          { label: "Admin", to: ADMIN_ROUTES.dashboard },
          { label: "Affiliates", to: ADMIN_ROUTES.affiliates },
          { label: "Withdrawals" },
        ]}
      />

      <Tabs tabs={TABS} activeKey={status} onChange={(k) => { setStatus(k); setPage(1); }} />

      <div className="glass p-6">
        <ResponsiveTable
          columns={columns}
          rows={data?.withdrawals ?? []}
          isLoading={isLoading}
          emptyState={<div className="py-10 text-center text-sm text-white/50">No withdrawals in this state.</div>}
          rowActions={(r) => (
            <div className="flex justify-end gap-2">
              {r.status === "requested" && (
                <Button size="sm" variant="ghost" onClick={() => handleProcess(r)}>Process</Button>
              )}
              {(r.status === "requested" || r.status === "processing") && (
                <>
                  <Button size="sm" onClick={() => setPayModal(r)}>Pay</Button>
                  <Button size="sm" variant="danger" onClick={() => setRejectModal(r)}>Reject</Button>
                </>
              )}
              {r.status === "paid" && (
                <Button size="sm" variant="ghost" leftIcon={<Download className="h-3.5 w-3.5" />} onClick={() => downloadReceipt(r)}>
                  Receipt
                </Button>
              )}
            </div>
          )}
        />
        <Pagination page={page} perPage={perPage} total={data?.total ?? 0} onPageChange={setPage} onPerPageChange={setPerPage} />
      </div>

      <PayModal withdrawal={payModal} onClose={() => setPayModal(null)} />
      <RejectModal withdrawal={rejectModal} onClose={() => setRejectModal(null)} />
    </div>
  );
}

function PayModal({ withdrawal, onClose }) {
  const [reference, setReference] = useState("");
  const [pay, { isLoading }] = usePayAffiliateWithdrawalMutation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!reference.trim()) {
      toast("Enter the M-Pesa reference.", { type: "error" });
      return;
    }
    try {
      await pay({ id: withdrawal.id, mpesa_reference: reference }).unwrap();
      toast("Withdrawal paid — receipt generated.", { type: "success" });
      setReference("");
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not mark as paid.", { type: "error" });
    }
  };

  return (
    <Modal
      isOpen={Boolean(withdrawal)}
      onClose={onClose}
      title="Mark withdrawal as paid"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} isLoading={isLoading}>Confirm paid</Button>
        </>
      }
    >
      {withdrawal && (
        <div className="space-y-4">
          <p className="text-sm text-white/60">
            After sending <strong className="text-white">{formatCurrency(withdrawal.net_amount)}</strong> to{" "}
            {withdrawal.affiliate_name} via M-Pesa, enter the transaction reference below. This generates the
            KRA-compliant receipt.
          </p>
          <Input label="M-Pesa reference" value={reference} onChange={(e) => setReference(e.target.value)} required />
        </div>
      )}
    </Modal>
  );
}

function RejectModal({ withdrawal, onClose }) {
  const [reason, setReason] = useState("");
  const [reject, { isLoading }] = useRejectAffiliateWithdrawalMutation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!reason.trim()) {
      toast("Enter a reason.", { type: "error" });
      return;
    }
    try {
      await reject({ id: withdrawal.id, reason }).unwrap();
      toast("Withdrawal rejected — funds released back to the affiliate's balance.", { type: "success" });
      setReason("");
      onClose();
    } catch {
      toast("Could not reject withdrawal.", { type: "error" });
    }
  };

  return (
    <Modal
      isOpen={Boolean(withdrawal)}
      onClose={onClose}
      title="Reject withdrawal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" onClick={handleSubmit} isLoading={isLoading}>Reject</Button>
        </>
      }
    >
      <Input label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} required />
    </Modal>
  );
}
