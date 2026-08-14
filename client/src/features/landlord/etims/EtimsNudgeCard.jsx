import { Link } from "react-router-dom";
import { ArrowRight, Landmark, X } from "lucide-react";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import {
  useGetPreferencesQuery,
  useUpdatePreferencesMutation,
} from "@/features/preferences/preferencesApiSlice";
import { useGetEtimsSettingsQuery } from "./etimsApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §4.4 — the one-time dashboard card.
//
// A neutral offer, dismissible forever, in ordinary card styling. Explicitly
// NOT a warning banner: nothing about it may suggest the landlord is behind on
// anything, because at this point they have not opted into anything at all.
const DISMISS_KEY = "etims_nudge_dismissed";

export default function EtimsNudgeCard() {
  const { data: prefs } = useGetPreferencesQuery();
  const { data: settings } = useGetEtimsSettingsQuery();
  const [updatePrefs] = useUpdatePreferencesMutation();

  // Hidden once dismissed, once the account has opted in (they've seen it and
  // acted), or while the platform switch is off.
  if (!prefs || !settings) return null;
  if (prefs[DISMISS_KEY]) return null;
  if (settings.account_enabled || !settings.features_enabled) return null;

  const dismiss = () => updatePrefs({ [DISMISS_KEY]: true });

  return (
    <div className="glass relative flex items-start gap-3 p-5">
      <Landmark size={20} className="mt-0.5 shrink-0 text-secondary" />
      <div className="flex-1 pr-6">
        <h3 className="text-sm font-medium text-white">New: KRA tax compliance tools</h3>
        <p className="mt-1 text-sm text-white/50">
          Record eTIMS invoices and get your monthly filing figure.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <Link
            to={LANDLORD_ROUTES.settings.taxCompliance}
            className="inline-flex items-center gap-1 text-sm text-secondary hover:underline"
          >
            Explore <ArrowRight size={14} />
          </Link>
          <Link
            to={LANDLORD_ROUTES.helpArticle("how-rental-taxes-work-in-kenya-the-basics")}
            className="text-sm text-white/50 hover:text-white"
          >
            See how it works
          </Link>
        </div>
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="absolute right-3 top-3 text-white/30 transition-colors hover:text-white/70"
      >
        <X size={16} />
      </button>
    </div>
  );
}
