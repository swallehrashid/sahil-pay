import { Download } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import { formatCurrency } from "@/utils/currencyFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { useGetPortalReceiptQuery } from "./tenantPortalApiSlice";

// View the receipt on screen first (same breakdown as the branded PDF), then
// download — mirroring the landlord's report generate → view → download flow.
function Section({ title, rows }) {
  if (!rows?.length) return null;
  return (
    <div className="mt-3">
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-white/50">{title}</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-white/40">
            <th className="py-1 font-medium">Item</th>
            <th className="py-1 text-right font-medium">Amount due</th>
            <th className="py-1 text-right font-medium">Paid</th>
            <th className="py-1 text-right font-medium">Balance c/f</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.invoice_number} className="border-t border-white/5 text-white/80">
              <td className="py-1.5">{r.description}</td>
              <td className="py-1.5 text-right">{formatCurrency(r.amount_due)}</td>
              <td className="py-1.5 text-right text-secondary">{formatCurrency(r.paid_this_receipt)}</td>
              <td className="py-1.5 text-right">{formatCurrency(r.balance_cf)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function TenantReceiptModal({ paymentId, onClose }) {
  const { data, isLoading } = useGetPortalReceiptQuery(paymentId, { skip: !paymentId });

  return (
    <Modal isOpen={!!paymentId} onClose={onClose} title="Payment receipt">
      {isLoading || !data ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl bg-white/5 p-4 text-sm">
            <p className="text-base font-medium text-white">{data.landlord?.company_name}</p>
            {data.landlord?.company_address && (
              <p className="text-xs text-white/50">{data.landlord.company_address}</p>
            )}
            <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-white/60">
              <span>Receipt: <span className="text-white/80">{data.payment_ref}</span></span>
              <span>Date: <span className="text-white/80">{data.payment_date}</span></span>
              <span>Tenant: <span className="text-white/80">{data.tenant_name}</span></span>
              <span>Unit: <span className="text-white/80">{[data.unit_name, data.property_name].filter(Boolean).join(" · ")}</span></span>
              <span>Method: <span className="text-white/80">{data.method}</span></span>
              <span>Ref: <span className="text-white/80">{data.reference}</span></span>
            </div>
          </div>

          <Section title="Rent" rows={data.rent_section} />
          <Section title="Utilities" rows={data.utilities_section} />
          <Section title="Other charges" rows={data.other_section} />

          <div className="space-y-1 border-t border-white/10 pt-3 text-sm">
            <div className="flex justify-between text-white/70">
              <span>Total amount due</span><span>{formatCurrency(data.total_due)}</span>
            </div>
            <div className="flex justify-between font-medium text-white">
              <span>Amount paid (this receipt)</span><span>{formatCurrency(data.amount_paid)}</span>
            </div>
            {data.advance_credit > 0 && (
              <div className="flex justify-between text-white/70">
                <span>Advance / credit</span><span>{formatCurrency(data.advance_credit)}</span>
              </div>
            )}
            <div className="flex justify-between font-semibold text-white">
              <span>Balance remaining</span><span>{formatCurrency(data.balance_remaining)}</span>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={onClose}>Close</Button>
            <Button
              leftIcon={<Download className="h-4 w-4" />}
              onClick={() => downloadFile(`/portal/payments/${paymentId}/receipt?format=pdf`, { filename: `receipt-${data.payment_ref}.pdf` })}
            >
              Download PDF
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
