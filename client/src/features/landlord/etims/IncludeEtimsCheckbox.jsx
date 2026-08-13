import { useEffect } from "react";
import Checkbox from "@/components/ui/Checkbox";
import {
  useGetPreferencesQuery,
  useUpdatePreferencesMutation,
} from "@/features/preferences/preferencesApiSlice";
import { useGetEtimsScopeQuery } from "./etimsApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §2.2 — the one small checkbox on every
// report/statement dialog.
//
// Renders NOTHING unless some in-scope property has eTIMS switched on, so a
// landlord who never opted in sees the report dialog exactly as it has always
// been. When it does render, the user's last choice is remembered per user, so
// an accountant who always wants the column ticks it once.
//
// Unticked means the generated document is byte-for-byte the current layout —
// no column, no footnote. The server enforces that too; this is only the
// request side of it.
const PREF_KEY = "report_include_etims";

export default function IncludeEtimsCheckbox({ value, onChange, propertyId }) {
  const { data: scope } = useGetEtimsScopeQuery();
  const { data: prefs } = useGetPreferencesQuery();
  const [updatePrefs] = useUpdatePreferencesMutation();

  // Adopt the remembered choice once preferences arrive, but never fight the
  // user: only seed while they haven't touched it this session.
  useEffect(() => {
    if (prefs && value === undefined) onChange(Boolean(prefs[PREF_KEY]));
  }, [prefs, value, onChange]);

  if (!scope?.enabled) return null;

  // Scoped to one property? Only offer it when THAT property is enabled.
  if (propertyId) {
    const ids = new Set((scope.properties ?? []).map((p) => String(p.id)));
    if (!ids.has(String(propertyId))) return null;
  }

  const handle = (checked) => {
    onChange(checked);
    updatePrefs({ [PREF_KEY]: checked });
  };

  return (
    <Checkbox
      label="Include eTIMS invoice numbers"
      checked={Boolean(value)}
      onChange={(e) => handle(e.target.checked)}
    />
  );
}

export { PREF_KEY as INCLUDE_ETIMS_PREF_KEY };
