import { Fragment } from "react";
import { Download } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import { formatCurrency } from "@/utils/currencyFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { useGetPortalReceiptQuery } from "./tenantPortalApiSlice";

// View the receipt on screen first (same breakdown as the branded PDF), then
// download — mirroring the landlord's report generate → view → download flow.
// Drawn as the same ruled tables as the PDF: details, charges, summary.
function ChargesTable({ groups }) {
  const shown = groups.filter(([, rows]) => rows?.length);
  if (!shown.length) return null;
  return (
    // Phones show Item + Paid; the due and carried-forward columns join from a
    // tablet up. The summary below always carries the balance, so nothing is lost.
    <div className="rounded-xl">
      <table className="doc-table">
        <thead>
          <tr>
            <th>Item</th>
            <th className="num hidden sm:table-cell">Amount due</th>
            <th className="num">Paid</th>
            <th className="num hidden sm:table-cell">Balance c/f</th>
          </tr>
        </thead>
        <tbody>
          {shown.map(([title, rows]) => (
            <Fragment key={title}>
              <tr className="group-row"><td colSpan={4}>{title}</td></tr>
              {rows.map((r, i) => (
                <tr key={`${title}-${r.invoice_number}-${i}`}>
                  <td>{r.description}</td>
                  <td className="num hidden sm:table-cell">{formatCurrency(r.amount_due)}</td>
                  <td className="num text-secondary-300">{formatCurrency(r.paid_this_receipt)}</td>
                  <td className="num hidden sm:table-cell">{formatCurrency(r.balance_cf)}</td>
                </tr>
              ))}
            </Fragment>
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
          <div className="flex items-center gap-3">
            {data.landlord?.logo_url && (
              <img src={data.landlord.logo_url} alt="" className="h-10 w-10 rounded-lg bg-white object-contain p-1" />
            )}
            <div className="min-w-0">
              <p className="text-base font-medium text-white">{data.landlord?.company_name}</p>
              {data.landlord?.company_address && (
                <p className="text-xs text-white/50">{data.landlord.company_address}</p>
              )}
            </div>
          </div>

          <table className="doc-table kv">
            <tbody>
              <tr><td>Receipt no.</td><td>{data.payment_ref}</td></tr>
              <tr><td>Date</td><td>{data.payment_date}</td></tr>
              <tr><td>Received from</td><td>{data.tenant_name}</td></tr>
              <tr><td>Unit</td><td>{[data.unit_name, data.property_name].filter(Boolean).join(" · ") || "—"}</td></tr>
              <tr><td>Method</td><td className="capitalize">{data.method || "—"}</td></tr>
              <tr><td>Reference</td><td className="break-all">{data.reference || "—"}</td></tr>
            </tbody>
          </table>

          <ChargesTable
            groups={[
              ["Rent", data.rent_section],
              ["Utilities", data.utilities_section],
              ["Deposits", data.deposits_section],
              ["Other charges", data.other_section],
            ]}
          />

          <table className="doc-table kv">
            <tbody>
              <tr><td>Total amount due</td><td className="num">{formatCurrency(data.total_due)}</td></tr>
              <tr className="total-row"><td>Amount paid (this receipt)</td><td className="num">{formatCurrency(data.amount_paid)}</td></tr>
              {data.advance_credit > 0 && (
                <tr><td>Advance / credit</td><td className="num">{formatCurrency(data.advance_credit)}</td></tr>
              )}
              <tr className="total-row"><td>Balance remaining</td><td className="num">{formatCurrency(data.balance_remaining)}</td></tr>
              {data.deposit_held_total > 0 && (
                <tr><td>Deposit held (refundable)</td><td className="num">{formatCurrency(data.deposit_held_total)}</td></tr>
              )}
            </tbody>
          </table>

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
