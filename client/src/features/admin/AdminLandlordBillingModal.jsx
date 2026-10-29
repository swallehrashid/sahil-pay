import { useEffect, useState } from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Spinner from "@/components/ui/Spinner";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetLandlordBillingQuery,
  useUpdateLandlordBillingMutation,
  useAddLandlordToCustomMutation,
  useSetLandlordFixedPriceMutation,
} from "./adminPricingApiSlice";

// #16/#17 — admin opens a landlord under a package: view their billing cycle, amount
// due, trial status/end and next billing date, edit any of them manually, or move them
// into the Custom package at a negotiated per-unit price. Changes reflect to the landlord.
// Exactly the server's SubscriptionStatus enum. "cancelled" used to be offered
// here and is not a real status — picking it returned an error (and, before the
// server validated, was silently replaced with "active" on save).
const STATUSES = ["trial", "active", "past_due", "suspended"];
// The server's pricing cycles. "yearly" is the legacy spelling of "annual" and
// is normalised server-side, but the picker offers the canonical names.
const CYCLES = [
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly (10% off)" },
  { value: "annual", label: "Annual (15% off)" },
];
// Who decides whether this landlord's portal is open.
const OVERRIDE_MODES = [
  { value: "system", label: "System decides (by balance)" },
  { value: "open", label: "Force OPEN — never lock" },
  { value: "closed", label: "Force CLOSED — always lock" },
];

// <input type="date"> only understands YYYY-MM-DD. Accept whatever the API
// hands back (ISO, or a legacy RFC-1123 string from older builds) so the
// current due date is actually VISIBLE instead of rendering as an empty field.
function d10(value) {
  if (!value) return "";
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10);
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toISOString().slice(0, 10);
}

export default function AdminLandlordBillingModal({ landlordId, onClose }) {
  const isOpen = landlordId != null;
  const { data, isLoading } = useGetLandlordBillingQuery(landlordId, { skip: !isOpen });
  const [updateBilling, { isLoading: isSaving }] = useUpdateLandlordBillingMutation();
  const [addToCustom, { isLoading: isAdding }] = useAddLandlordToCustomMutation();
  const [setFixedPrice, { isLoading: isSettingFixed }] = useSetLandlordFixedPriceMutation();

  const [form, setForm] = useState({});
  const [customPrice, setCustomPrice] = useState("");
  const [fixedPrice, setFixedPrice_] = useState("");
  const [fixedReason, setFixedReason] = useState("");

  useEffect(() => {
    if (data) {
      setForm({
        amount_due: data.subscription?.amount_due ?? "",
        next_billing_date: d10(data.subscription?.next_billing_date),
        status: data.subscription?.status ?? "active",
        billing_cycle: data.subscription?.billing_cycle ?? "monthly",
        is_on_trial: Boolean(data.is_on_trial),
        trial_ends_at: d10(data.trial_ends_at),
        access_override_until: d10(data.subscription?.access_override_until),
        access_override_reason: data.subscription?.access_override_reason ?? "",
        admin_override_mode: data.subscription?.admin_override_mode ?? "system",
        admin_status_locked: Boolean(data.subscription?.admin_status_locked),
        admin_billing_frozen: Boolean(data.subscription?.admin_billing_frozen),
        admin_override_reason: data.subscription?.admin_override_reason ?? "",
      });
      setCustomPrice(data.per_unit_price ?? "");
      setFixedPrice_(data.fixed_monthly_price ?? "");
    }
  }, [data]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    try {
      await updateBilling({
        id: landlordId,
        amount_due: form.amount_due === "" ? undefined : Number(form.amount_due),
        next_billing_date: form.next_billing_date || undefined,
        status: form.status,
        billing_cycle: form.billing_cycle,
        is_on_trial: form.is_on_trial,
        trial_ends_at: form.trial_ends_at || null,
        access_override_until: form.access_override_until || null,
        access_override_reason: form.access_override_reason || null,
        admin_override_mode: form.admin_override_mode || "system",
        admin_status_locked: Boolean(form.admin_status_locked),
        admin_billing_frozen: Boolean(form.admin_billing_frozen),
        admin_override_reason: form.admin_override_reason || null,
      }).unwrap();
      toast("Saved. These settings are pinned — the system will not change them.",
            { type: "success" });
      onClose();
    } catch (err) {
      const fields = err?.data?.errors;
      if (fields && typeof fields === "object") {
        // Name the field that needs fixing rather than a generic failure.
        toast(Object.entries(fields).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join("  •  "),
              { type: "error" });
      } else {
        toast(err?.data?.error || "Could not update billing.", { type: "error" });
      }
    }
  };

  const saveFixedPrice = async (clear = false) => {
    if (!fixedReason.trim()) {
      toast("Give a reason — it goes on the audit trail.", { type: "error" });
      return;
    }
    try {
      await setFixedPrice({
        id: landlordId,
        fixed_monthly_price: clear ? null : Number(fixedPrice),
        reason: fixedReason.trim(),
      }).unwrap();
      if (clear) setFixedPrice_("");
      setFixedReason("");
      toast(
        clear
          ? "Fixed price cleared — per-unit pricing resumes next cycle."
          : "Fixed price set. It takes effect on the next billing cycle.",
        { type: "success" }
      );
    } catch (err) {
      toast(err?.data?.error || "Could not set the fixed price.", { type: "error" });
    }
  };

  const moveToCustom = async () => {
    if (!customPrice) {
      toast("Enter a per-unit price.", { type: "error" });
      return;
    }
    try {
      await addToCustom({ id: landlordId, per_unit_price: Number(customPrice) }).unwrap();
      toast("Landlord moved to the Custom package.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not add to Custom.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Landlord billing">
      {isLoading || !data ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-white">{data.company_name}</p>
              <p className="text-xs text-white/50">
                Package: {data.package?.name ?? "—"}
                {data.is_custom_package && " (Custom)"}
              </p>
            </div>
            {data.is_on_trial && <Badge color="amber">On trial</Badge>}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Input label="Amount due" type="number" step="0.01" value={form.amount_due} onChange={set("amount_due")} />
            <Input label="Next billing date" type="date" value={form.next_billing_date} onChange={set("next_billing_date")} />
            <Select
              label="Status"
              value={form.status}
              onChange={set("status")}
              options={STATUSES.map((s) => ({ value: s, label: s }))}
            />
            <Select
              label="Billing cycle"
              value={form.billing_cycle}
              onChange={set("billing_cycle")}
              options={CYCLES}
            />
          </div>

          <div className="flex items-center gap-6">
            <Checkbox
              label="Trial active"
              checked={Boolean(form.is_on_trial)}
              onChange={(e) => setForm((f) => ({ ...f, is_on_trial: e.target.checked }))}
            />
            <Input label="Trial ends" type="date" value={form.trial_ends_at} onChange={set("trial_ends_at")} className="flex-1" />
          </div>

          {/* ADMIN OVERRIDE — the owner's decision, which the system obeys. */}
          <div className="space-y-3 rounded-xl border border-secondary/30 bg-secondary/[0.06] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wide text-white/70">
                Admin control — overrides the system
              </p>
              {form.admin_override_mode === "open" && <Badge color="emerald">Forced open</Badge>}
              {form.admin_override_mode === "closed" && <Badge color="secondary">Forced closed</Badge>}
            </div>
            <p className="text-xs leading-relaxed text-white/55">
              Whatever you set here wins over the balance, the grace period, the status and the trial.
              Use it when the commercial reality is not what the system has worked out.
            </p>
            <Select
              label="Portal access"
              value={form.admin_override_mode ?? "system"}
              onChange={set("admin_override_mode")}
              options={OVERRIDE_MODES}
            />
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-6">
              <Checkbox
                label="Pin status (system never changes it)"
                checked={Boolean(form.admin_status_locked)}
                onChange={(e) => setForm((f) => ({ ...f, admin_status_locked: e.target.checked }))}
              />
              <Checkbox
                label="Freeze billing (no auto charges, date never moves)"
                checked={Boolean(form.admin_billing_frozen)}
                onChange={(e) => setForm((f) => ({ ...f, admin_billing_frozen: e.target.checked }))}
              />
            </div>
            <Input
              label="Reason (kept on the audit trail)"
              value={form.admin_override_reason}
              onChange={set("admin_override_reason")}
              placeholder="e.g. Pays cash monthly — keep open"
            />
          </div>

          {/* Installments: account state and the exemption that keeps it open. */}
          <div className="space-y-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wide text-white/60">Account access</p>
              {data.access?.reason === "admin_closed"
                ? <Badge color="secondary">Locked — closed by admin</Badge>
                : data.access?.locked
                  ? <Badge color="secondary">Locked — unpaid balance</Badge>
                  : data.access?.override_until
                    ? <Badge color="amber">Open by exemption until {data.access.override_until}</Badge>
                    : <Badge color="emerald">Open</Badge>}
            </div>
            <p className="text-xs leading-relaxed text-white/55">
              Balance {data.access?.balance?.toLocaleString?.() ?? "—"} KES
              {data.access?.balance_due_since ? ` · owing since ${data.access.balance_due_since}` : ""}
              {data.access?.grace_until ? ` · grace ends ${data.access.grace_until}` : ""}.
              An exemption keeps the account open until the date you set; the balance stays and is added
              to the next month's charge.
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Input label="Keep open until" type="date" value={form.access_override_until} onChange={set("access_override_until")} />
              <Input label="Reason" value={form.access_override_reason} onChange={set("access_override_reason")}
                     placeholder="e.g. Paid 6,000 of 10,000 — balance next month" />
            </div>
          </div>

          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={save} isLoading={isSaving}>Save billing</Button>
          </div>

          {/* A negotiated flat monthly fee — the strongest override there is. */}
          <div className="mt-2 space-y-2 rounded-xl border border-secondary/30 bg-secondary/[0.06] p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-secondary-100">
              Fixed monthly price
            </p>
            <p className="text-xs leading-relaxed text-white/55">
              A flat fee agreed with this client. Overrides per-unit pricing
              entirely — adding units never changes it — and carries{" "}
              <strong className="text-white/75">no cycle discount</strong>,
              since the figure is already the negotiated one. Takes effect on
              the next billing cycle.
            </p>
            <div className="flex items-end gap-3">
              <Input
                label="Fixed price / month"
                type="number"
                step="0.01"
                value={fixedPrice}
                onChange={(e) => setFixedPrice_(e.target.value)}
                className="flex-1"
              />
              <Input
                label="Reason"
                value={fixedReason}
                onChange={(e) => setFixedReason(e.target.value)}
                placeholder="Agreed on call, 20 units"
                className="flex-1"
              />
            </div>
            <div className="flex gap-2">
              <Button
                onClick={() => saveFixedPrice(false)}
                isLoading={isSettingFixed}
                disabled={!fixedPrice}
              >
                Set fixed price
              </Button>
              {data.fixed_monthly_price && (
                <Button variant="ghost" onClick={() => saveFixedPrice(true)}>
                  Clear
                </Button>
              )}
            </div>
          </div>

          {/* #17 — move into the Custom package at a negotiated per-unit price */}
          <div className="mt-2 space-y-2 rounded-xl border border-white/10 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-white/40">Custom package</p>
            <p className="text-xs text-white/50">
              Move this landlord to the private Custom package and set their per-unit price.
            </p>
            <div className="flex items-end gap-3">
              <Input
                label="Per-unit price"
                type="number"
                step="0.01"
                value={customPrice}
                onChange={(e) => setCustomPrice(e.target.value)}
                className="flex-1"
              />
              <Button variant="ghost" onClick={moveToCustom} isLoading={isAdding}>
                {data.is_custom_package ? "Update price" : "Add to Custom"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
