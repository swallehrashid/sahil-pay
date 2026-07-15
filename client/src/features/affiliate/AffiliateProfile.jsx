import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import { toast } from "@/components/ui/Toast";
import { useGetAffiliateProfileQuery, useUpdateAffiliateProfileMutation } from "./affiliateApiSlice";

export default function AffiliateProfile() {
  const { data, isLoading } = useGetAffiliateProfileQuery();
  const [update, { isLoading: isSaving }] = useUpdateAffiliateProfileMutation();

  const [prev, setPrev] = useState();
  const [form, setForm] = useState(null);
  if (data?.affiliate && data.affiliate !== prev) {
    setPrev(data.affiliate);
    setForm(data.affiliate);
  }

  if (isLoading || !form) return <Spinner className="mx-auto my-10" />;

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await update({
        full_name: form.full_name,
        phone: form.phone,
        mpesa_number: form.mpesa_number,
        national_id: form.national_id,
        kra_pin: form.kra_pin,
      }).unwrap();
      toast("Profile updated.", { type: "success" });
    } catch {
      toast("Could not update profile.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Profile" subtitle="Your payout details — required before you can withdraw" />
      <form onSubmit={handleSubmit} className="glass max-w-xl space-y-4 p-6">
        <Input label="Full name" value={form.full_name ?? ""} onChange={set("full_name")} required />
        <Input label="Phone" value={form.phone ?? ""} onChange={set("phone")} required />
        <Input
          label="M-Pesa number (for withdrawals)"
          value={form.mpesa_number ?? ""}
          onChange={set("mpesa_number")}
          hint="Changing this is logged for security — you'll want to keep it accurate to avoid delayed payouts."
        />
        <Input label="National ID" value={form.national_id ?? ""} onChange={set("national_id")} hint="Required by KRA for your payout receipts." />
        <Input label="KRA PIN (optional)" value={form.kra_pin ?? ""} onChange={set("kra_pin")} />
        <div className="flex justify-end">
          <Button type="submit" isLoading={isSaving}>
            Save changes
          </Button>
        </div>
      </form>

      <div className="glass max-w-xl space-y-2 p-6">
        <h3 className="text-sm font-medium text-white/70">Account</h3>
        <Row label="Referral code" value={form.referral_code} />
        <Row label="Status" value={form.status} />
        <Row label="Commission rate" value={form.commission_rate_override ? `${form.commission_rate_override}% (custom)` : "Default program rate"} />
        <Row label="Commission months" value={form.commission_months_override ?? "Default program months"} />
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-white/50">{label}</span>
      <span className="capitalize text-white/80">{value}</span>
    </div>
  );
}
