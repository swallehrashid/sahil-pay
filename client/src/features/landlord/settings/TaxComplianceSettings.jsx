import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Landmark } from "lucide-react";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import {
  useGetEtimsSettingsQuery,
  useUpdateEtimsSettingsMutation,
  useUpdatePropertyEtimsSettingsMutation,
} from "@/features/landlord/etims/etimsApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §2.1 — the opt-in surface for the whole
// KRA layer.
//
// This page is the ONE place that talks about compliance to a landlord who
// hasn't opted in, and even here the tone is an offer, not a prompt. Nothing
// on this screen counts what they haven't done or warns them about anything.
export default function TaxComplianceSettings() {
  const { data, isLoading } = useGetEtimsSettingsQuery();
  const [updateAccount, { isLoading: isSavingAccount }] = useUpdateEtimsSettingsMutation();
  const [updateProperty] = useUpdatePropertyEtimsSettingsMutation();

  const [accountPin, setAccountPin] = useState("");
  const [pins, setPins] = useState({});

  useEffect(() => {
    if (data) {
      setAccountPin(data.account_kra_pin ?? "");
      setPins(Object.fromEntries((data.properties ?? []).map((p) => [p.id, p.kra_pin ?? ""])));
    }
  }, [data]);

  if (isLoading || !data) return <SkeletonForm fields={5} />;

  // The platform kill switch. When it's off the feature genuinely does not
  // exist for anyone, so we say so plainly rather than showing dead controls.
  if (!data.features_enabled) {
    return (
      <div className="glass p-6 text-sm text-white/50">
        KRA and eTIMS features are not currently available on this platform.
      </div>
    );
  }

  const saveAccount = async (patch) => {
    try {
      await updateAccount(patch).unwrap();
      toast("Tax compliance settings saved.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not save those settings.", { type: "error" });
    }
  };

  const saveProperty = async (propertyId, patch) => {
    try {
      await updateProperty({ propertyId, ...patch }).unwrap();
      toast("Saved.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not save that property.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      {/* --- Master switch ------------------------------------------------ */}
      <div className="glass space-y-3 p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
          <Landmark size={20} className="mt-0.5 hidden shrink-0 text-secondary sm:block" />
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-medium text-white">Enable eTIMS &amp; KRA features</h3>
            <p className="mt-1 text-sm text-white/50">
              Record the eTIMS invoice numbers you issue through KRA, and get your
              monthly rental income figure for filing. Everything stays off until
              you switch on the properties you want it for.
            </p>
            <Link
              to={`${LANDLORD_ROUTES.helpArticle("how-rental-taxes-work-in-kenya-the-basics")}`}
              className="mt-2 inline-flex items-center gap-1 text-sm text-secondary hover:underline"
            >
              New to eTIMS? Read the step-by-step guides <ArrowRight size={14} />
            </Link>
          </div>
          <Button
            type="button"
            className="shrink-0"
            variant={data.account_enabled ? "primary" : "ghost"}
            disabled={isSavingAccount}
            onClick={() => saveAccount({ account_enabled: !data.account_enabled })}
          >
            {data.account_enabled ? "Enabled" : "Enable"}
          </Button>
        </div>
      </div>

      {/* Everything below only exists once they've opted in. Rendering it
          disabled would be a standing reminder of a decision they already made. */}
      {data.account_enabled && (
        <>
          {/* --- Your own PIN -------------------------------------------- */}
          <div className="glass space-y-3 p-6">
            <h3 className="text-base font-medium text-white">Your KRA PIN</h3>
            <p className="text-sm text-white/50">
              Used on invoices you issue in your own name — for a property manager,
              that means your commission invoices. Optional.
            </p>
            <div className="flex flex-col gap-3 sm:max-w-md sm:flex-row sm:items-end">
              <Input
                label="KRA PIN"
                value={accountPin}
                placeholder="A012345678B"
                onChange={(e) => setAccountPin(e.target.value.toUpperCase())}
              />
              <Button
                type="button"
                className="shrink-0"
                disabled={isSavingAccount}
                onClick={() => saveAccount({ account_kra_pin: accountPin })}
              >
                Save
              </Button>
            </div>
          </div>

          {/* --- Reminders ------------------------------------------------ */}
          <div className="glass space-y-3 p-6">
            <h3 className="text-base font-medium text-white">Monthly reminders</h3>
            <div className="space-y-2">
              <Checkbox
                label="Around the 5th — a nudge that you can record this month's eTIMS invoices"
                checked={data.reminders.record_invoices}
                onChange={(e) =>
                  saveAccount({ reminders: { record_invoices: e.target.checked } })
                }
              />
              <Checkbox
                label="On the 15th — that last month's 7.5% is due at KRA by the 20th"
                checked={data.reminders.filing_due}
                onChange={(e) =>
                  saveAccount({ reminders: { filing_due: e.target.checked } })
                }
              />
            </div>
          </div>

          {/* --- Per-property -------------------------------------------- */}
          <div className="glass space-y-4 p-6">
            <div>
              <h3 className="text-base font-medium text-white">Properties</h3>
              <p className="mt-1 text-sm text-white/50">
                Switch on the properties you issue eTIMS invoices for. The owner&apos;s
                KRA PIN is the seller on their rent invoices, even when you collect
                the rent.
              </p>
            </div>

            <div className="space-y-3">
              {(data.properties ?? []).map((property) => (
                <div key={property.id} className="rounded-lg border border-white/10 p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="text-sm font-medium text-white">{property.name}</div>
                      {property.owner_name && (
                        <div className="text-xs text-white/40">Owner: {property.owner_name}</div>
                      )}
                    </div>
                    <Button
                      type="button"
                      className="shrink-0"
                      variant={property.etims_enabled ? "primary" : "ghost"}
                      onClick={() =>
                        saveProperty(property.id, { etims_enabled: !property.etims_enabled })
                      }
                    >
                      {property.etims_enabled ? "On" : "Off"}
                    </Button>
                  </div>

                  {property.etims_enabled && (
                    <div className="mt-4 space-y-3 border-t border-white/10 pt-4">
                      <div className="flex flex-col gap-3 sm:max-w-md sm:flex-row sm:items-end">
                        <Input
                          label="Owner's KRA PIN"
                          value={pins[property.id] ?? ""}
                          placeholder={property.owner_kra_pin || "A012345678B"}
                          onChange={(e) =>
                            setPins((prev) => ({
                              ...prev,
                              [property.id]: e.target.value.toUpperCase(),
                            }))
                          }
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          className="shrink-0"
                          onClick={() =>
                            saveProperty(property.id, { kra_pin: pins[property.id] })
                          }
                        >
                          Save PIN
                        </Button>
                      </div>

                      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:gap-4">
                        {[
                          ["show_on_receipts", "Show on receipts"],
                          ["show_on_statements", "Show on statements"],
                          ["show_on_reports", "Show on reports"],
                        ].map(([key, label]) => (
                          <Checkbox
                            key={key}
                            label={label}
                            checked={property.display[key]}
                            onChange={(e) =>
                              saveProperty(property.id, {
                                display: { [key]: e.target.checked },
                              })
                            }
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
