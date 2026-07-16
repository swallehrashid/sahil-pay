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
  usePayAffiliateWithdrawalMutation, usePayAffiliateWithdrawalB2cMutation,
  useRejectAffiliateWithdrawalMutation,
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
    {
      key: "status",
      header: "Status",
      render: (r) => (
        <div className="flex items-center gap-2">
          <StatusBadge status={r.status} />
          {r.b2c_status && r.b2c_status !== "result_received" && (
            <StatusBadge status={r.b2c_status} />
          )}
        </div>
      ),
    },
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
  const [mode, setMode] = useState("b2c"); // 'b2c' | 'manual'
  const [reference, setReference] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [pay, { isLoading: isPayingManual }] = usePayAffiliateWithdrawalMutation();
  const [payB2c, { isLoading: isPayingB2c }] = usePayAffiliateWithdrawalB2cMutation();

  const reset = () => { setReference(""); setConfirmText(""); setMode("b2c"); };
  const close = () => { reset(); onClose(); };

  const handleManual = async (e) => {
    e.preventDefault();
    if (!reference.trim()) {
      toast("Enter the M-Pesa reference.", { type: "error" });
      return;
    }
    try {
      await pay({ id: withdrawal.id, mpesa_reference: reference }).unwrap();
      toast("Withdrawal paid — receipt generated.", { type: "success" });
      close();
    } catch (err) {
      toast(err?.data?.error || "Could not mark as paid.", { type: "error" });
    }
  };

  const handleB2c = async () => {
    if (confirmText.trim().toUpperCase() !== "PAY") {
      toast('Type "PAY" to confirm.', { type: "error" });
      return;
    }
    try {
      const res = await payB2c({ id: withdrawal.id }).unwrap();
      toast(res?.simulated ? "B2C payout simulated and paid." : "B2C payout initiated — awaiting confirmation.", { type: "success" });
      close();
    } catch (err) {
      toast(err?.data?.error || "Could not initiate B2C payout.", { type: "error" });
    }
  };

  const wholeAmount = withdrawal ? Math.floor(Number(withdrawal.net_amount)) : 0;
  const remainder = withdrawal ? Number(withdrawal.net_amount) - wholeAmount : 0;
  const maskedNumber = withdrawal?.affiliate_mpesa_number
    ? withdrawal.affiliate_mpesa_number.replace(/(\d{6})\d{3}(\d{2})$/, "$1***$2")
    : "—";

  return (
    <Modal
      isOpen={Boolean(withdrawal)}
      onClose={close}
      title="Pay withdrawal"
      footer={
        mode === "b2c" ? (
          <>
            <Button variant="ghost" onClick={close}>Cancel</Button>
            <Button onClick={handleB2c} isLoading={isPayingB2c}>Send via M-Pesa</Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={close}>Cancel</Button>
            <Button onClick={handleManual} isLoading={isPayingManual}>Confirm paid</Button>
          </>
        )
      }
    >
      {withdrawal && (
        <div className="space-y-4">
          <div className="flex gap-2 rounded-lg bg-white/5 p-1 text-sm">
            <button
              type="button"
              onClick={() => setMode("b2c")}
              className={`flex-1 rounded-md px-3 py-1.5 ${mode === "b2c" ? "bg-secondary text-black" : "text-white/60"}`}
            >
              Send via M-Pesa (B2C)
            </button>
            <button
              type="button"
              onClick={() => setMode("manual")}
              className={`flex-1 rounded-md px-3 py-1.5 ${mode === "manual" ? "bg-secondary text-black" : "text-white/60"}`}
            >
              Record manual payment
            </button>
          </div>

          {mode === "b2c" ? (
            <div className="space-y-3">
              <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-sm">
                <div className="flex justify-between py-1">
                  <span className="text-white/50">Affiliate</span>
                  <span className="text-white">{withdrawal.affiliate_name}</span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-white/50">M-Pesa number</span>
                  <span className="font-mono text-white">{maskedNumber}</span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-white/50">Net amount</span>
                  <span className="text-white">{formatCurrency(withdrawal.net_amount)}</span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-white/50">Amount sent (whole shillings)</span>
                  <span className="font-medium text-white">{formatCurrency(wholeAmount)}</span>
                </div>
                {remainder > 0 && (
                  <p className="mt-1 text-xs text-white/40">
                    KES {remainder.toFixed(2)} remainder stays in the program ledger — B2C only sends whole shillings.
                  </p>
                )}
              </div>
              {withdrawal.b2c_status === "failed" && withdrawal.b2c_result_desc && (
                <p className="text-xs text-rose-400">Last attempt failed: {withdrawal.b2c_result_desc}</p>
              )}
              <Input
                label='Type "PAY" to confirm'
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder="PAY"
              />
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-white/60">
                After sending <strong className="text-white">{formatCurrency(withdrawal.net_amount)}</strong> to{" "}
                {withdrawal.affiliate_name} via M-Pesa, enter the transaction reference below. This generates the
                KRA-compliant receipt.
              </p>
              <Input label="M-Pesa reference" value={reference} onChange={(e) => setReference(e.target.value)} required />
            </div>
          )}
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
