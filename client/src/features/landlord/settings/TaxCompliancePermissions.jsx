import { useEffect, useState } from "react";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import { toast } from "@/components/ui/Toast";
import {
  useGetEtimsScopeQuery,
  useGetTaxPermissionsQuery,
  useSetTaxPermissionsMutation,
} from "@/features/landlord/etims/etimsApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §5.2 — granting a team member
// `manage_tax_compliance` on specific properties.
//
// Only rendered for a SAVED member (a grant needs an id to hang off) and only
// when the account has eTIMS-enabled properties to grant. An account that
// hasn't opted in sees no tax section on the team form at all — not a disabled
// one, not one explaining what they're missing.
export default function TaxCompliancePermissions({ memberId, memberName }) {
  const { data: scope } = useGetEtimsScopeQuery();
  const { data, isLoading } = useGetTaxPermissionsQuery(memberId, { skip: !memberId });
  const [save, { isLoading: isSaving }] = useSetTaxPermissionsMutation();

  const [selected, setSelected] = useState([]);

  useEffect(() => {
    if (data?.property_ids) setSelected(data.property_ids);
  }, [data]);

  if (!memberId || !scope?.enabled || isLoading) return null;

  const properties = scope.properties ?? [];
  const allSelected = properties.length > 0 && selected.length === properties.length;

  const toggle = (id) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));

  const handleSave = async () => {
    try {
      await save({ memberId, propertyIds: selected }).unwrap();
      toast("Tax compliance access saved.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not save tax compliance access.", { type: "error" });
    }
  };

  const grant = data?.grants?.[0];

  return (
    <div className="border-t border-white/10 pt-4">
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-white/40">
        Tax compliance
      </p>
      <p className="mb-3 text-sm text-white/50">
        Properties {memberName || "this member"} may record eTIMS invoice numbers
        for, and pull the KRA report on. Everything else stays hidden from them.
      </p>

      <Checkbox
        label="Select all properties"
        checked={allSelected}
        onChange={(e) => setSelected(e.target.checked ? properties.map((p) => p.id) : [])}
      />

      <div className="glass mt-3 max-h-40 space-y-1 overflow-y-auto p-3">
        {properties.map((property) => (
          <Checkbox
            key={property.id}
            label={property.name}
            checked={selected.includes(property.id)}
            onChange={() => toggle(property.id)}
            className="w-full px-2 py-1.5"
          />
        ))}
      </div>

      <div className="mt-3 flex items-center gap-3">
        <Button type="button" size="sm" onClick={handleSave} isLoading={isSaving}>
          Save tax access
        </Button>
        {grant?.granted_at && (
          <span className="text-xs text-white/40">
            Last granted {grant.granted_at.slice(0, 10)}
          </span>
        )}
      </div>
    </div>
  );
}
