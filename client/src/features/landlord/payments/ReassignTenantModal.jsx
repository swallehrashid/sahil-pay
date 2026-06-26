import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useReassignPaymentTenantMutation } from "./paymentApiSlice";
import { isRequired } from "@/utils/validators";

// "Change tenant" row action — re-allocates a payment to a different tenant.
export default function ReassignTenantModal({ payment, tenants = [], onClose }) {
  const [reassign, { isLoading }] = useReassignPaymentTenantMutation();
  const [tenantId, setTenantId] = useState("");
  const [error, setError] = useState("");

  if (!payment) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isRequired(tenantId)) {
      setError("Select a tenant");
      return;
    }
    setError("");
    try {
      await reassign({ id: payment.id, tenant_id: tenantId }).unwrap();
      toast("Payment reassigned.", { type: "success" });
      onClose();
    } catch {
      toast("Could not reassign the payment.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title="Change tenant">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-white/50">
          Payment {payment.payment_ref} is currently allocated to {payment.tenant_name ?? "no tenant"}.
        </p>
        <Select
          label="New tenant"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          error={error}
          options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
          required
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Reassign
          </Button>
        </div>
      </form>
    </Modal>
  );
}
