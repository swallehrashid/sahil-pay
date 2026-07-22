import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Ban, RotateCcw, Wrench, Smartphone, MessageSquarePlus } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Textarea from "@/components/ui/Textarea";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import { useGetAdminLandlordQuery, useSuspendLandlordMutation, useReactivateLandlordMutation, useCorrectDataMutation } from "./adminApiSlice";
import { useCreditLandlordSmsMutation } from "./adminSmsApiSlice";
import { ADMIN_ROUTES } from "@/config/routePaths";

const CORRECTION_ENTITY_TYPES = [
  { value: "tenant", label: "Tenant" },
  { value: "payment", label: "Payment" },
  { value: "invoice", label: "Invoice" },
];

// §7 — drill into one account; suspend/reactivate after investigation, or correct data.
export default function LandlordDetail() {
  const { id } = useParams();
  const { data, isLoading } = useGetAdminLandlordQuery(id);
  const [suspend, { isLoading: isSuspending }] = useSuspendLandlordMutation();
  const [reactivate, { isLoading: isReactivating }] = useReactivateLandlordMutation();
  const [correctData, { isLoading: isCorrecting }] = useCorrectDataMutation();
  const [creditSms, { isLoading: isCrediting }] = useCreditLandlordSmsMutation();

  // Manual SMS credit (landlord paid the operator directly, before automated billing).
  const [isCreditOpen, setIsCreditOpen] = useState(false);
  const [smsCredit, setSmsCredit] = useState({ credits: "", reason: "" });
  const [smsCreditError, setSmsCreditError] = useState("");

  const handleCreditSms = async (e) => {
    e.preventDefault();
    const credits = Number(smsCredit.credits);
    if (!Number.isInteger(credits) || credits === 0) {
      setSmsCreditError("Enter a non-zero whole number of SMS (negative to correct a mistake).");
      return;
    }
    if (!smsCredit.reason.trim()) {
      setSmsCreditError("A reason/reference is required (e.g. 'M-Pesa 100 KES, code ABC123').");
      return;
    }
    setSmsCreditError("");
    try {
      const res = await creditSms({ landlordId: Number(id), credits, reason: smsCredit.reason }).unwrap();
      toast(`SMS balance updated — now ${res.sms_balance.toLocaleString()}.`, { type: "success" });
      setIsCreditOpen(false);
      setSmsCredit({ credits: "", reason: "" });
    } catch (err) {
      toast(err?.data?.error || "Could not credit the SMS balance.", { type: "error" });
    }
  };

  const [isCorrectOpen, setIsCorrectOpen] = useState(false);
  const [correction, setCorrection] = useState({ entity_type: "tenant", entity_id: "", correction_json: "{}", reason: "" });
  const [correctionError, setCorrectionError] = useState("");

  // Suspend/reactivate both require a mandatory reason — collected via the same dialog.
  const [pendingStatusChange, setPendingStatusChange] = useState(null); // "suspend" | "reactivate" | null
  const [statusReason, setStatusReason] = useState("");

  const handleConfirmStatusChange = async () => {
    if (!statusReason.trim()) {
      toast("A reason is required.", { type: "error" });
      return;
    }
    try {
      if (pendingStatusChange === "suspend") {
        await suspend({ id, reason: statusReason }).unwrap();
        toast("Account suspended.", { type: "success" });
      } else {
        await reactivate({ id, reason: statusReason }).unwrap();
        toast("Account reactivated.", { type: "success" });
      }
      setPendingStatusChange(null);
      setStatusReason("");
    } catch {
      toast(`Could not ${pendingStatusChange} the account.`, { type: "error" });
    }
  };

  const handleCorrect = async (e) => {
    e.preventDefault();
    let parsedCorrection;
    try {
      parsedCorrection = JSON.parse(correction.correction_json);
    } catch {
      setCorrectionError("Correction must be valid JSON, e.g. {\"notes\": \"fixed typo\"}");
      return;
    }
    if (!correction.entity_id || !correction.reason.trim()) {
      setCorrectionError("Entity ID and reason are required.");
      return;
    }
    setCorrectionError("");
    try {
      await correctData({
        landlord_id: Number(id),
        entity_type: correction.entity_type,
        entity_id: Number(correction.entity_id),
        correction: parsedCorrection,
        reason: correction.reason,
      }).unwrap();
      toast("Correction logged.", { type: "success" });
      setIsCorrectOpen(false);
      setCorrection({ entity_type: "tenant", entity_id: "", correction_json: "{}", reason: "" });
    } catch {
      toast("Could not submit the correction.", { type: "error" });
    }
  };

  return (
    <div>
      <PageHeader
        title={data?.company_name ?? "Landlord detail"}
        subtitle="Drill into this account"
        breadcrumbs={[{ label: "Landlords", to: ADMIN_ROUTES.landlords }, { label: "Detail" }]}
        actions={
          <>
            <Link to={ADMIN_ROUTES.landlords}>
              <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
                Back
              </Button>
            </Link>
            <Button variant="ghost" leftIcon={<Wrench className="h-4 w-4" />} onClick={() => setIsCorrectOpen(true)}>
              Correct data
            </Button>
            <Button variant="ghost" leftIcon={<MessageSquarePlus className="h-4 w-4" />} onClick={() => setIsCreditOpen(true)}>
              Add SMS credit
            </Button>
            <Link to={`${ADMIN_ROUTES.copilot}?tab=landlords&landlord_id=${id}`}>
              <Button variant="ghost" leftIcon={<Smartphone className="h-4 w-4" />}>
                Co-pilot
              </Button>
            </Link>
            {data?.is_active ? (
              <Button variant="danger" leftIcon={<Ban className="h-4 w-4" />} onClick={() => setPendingStatusChange("suspend")}>
                Suspend
              </Button>
            ) : (
              <Button leftIcon={<RotateCcw className="h-4 w-4" />} onClick={() => setPendingStatusChange("reactivate")}>
                Reactivate
              </Button>
            )}
          </>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Status" value={<Badge color={data?.is_active ? "emerald" : "secondary"}>{data?.is_active ? "Active" : "Suspended"}</Badge>} />
          <SummaryCard label="Units" value={data?.unit_count ?? 0} accent="third" />
          <SummaryCard label="Active tenants" value={data?.active_tenants ?? 0} accent="third" />
          <SummaryCard label="Team members" value={data?.team_members?.length ?? 0} accent="third" />
          <SummaryCard label="SMS balance" value={(data?.sms_balance ?? 0).toLocaleString()} accent="third" />
        </div>
      )}

      <ConfirmDialog
        isOpen={Boolean(pendingStatusChange)}
        onClose={() => { setPendingStatusChange(null); setStatusReason(""); }}
        onConfirm={handleConfirmStatusChange}
        title={pendingStatusChange === "suspend" ? "Suspend this account?" : "Reactivate this account?"}
        description="This is recorded in the audit trail with your reason."
        isDangerous={pendingStatusChange === "suspend"}
        isLoading={isSuspending || isReactivating}
        confirmLabel={pendingStatusChange === "suspend" ? "Suspend" : "Reactivate"}
      >
        <Textarea
          label="Reason"
          value={statusReason}
          onChange={(e) => setStatusReason(e.target.value)}
          rows={3}
          required
          className="mt-3"
        />
      </ConfirmDialog>

      <Modal isOpen={isCreditOpen} onClose={() => setIsCreditOpen(false)} title="Add SMS credit">
        <form onSubmit={handleCreditSms} className="space-y-4">
          <p className="text-sm text-white/60">
            Current balance: <span className="text-white">{(data?.sms_balance ?? 0).toLocaleString()}</span> SMS.
            Use this when a landlord has paid you directly (e.g. via M-Pesa) before automated billing is live.
            At the current rate 1 KES = 1 SMS credit.
          </p>
          <Input
            label="SMS credits to add"
            type="number"
            hint="Whole number. Use a negative value to correct a mistaken credit."
            value={smsCredit.credits}
            onChange={(e) => setSmsCredit((c) => ({ ...c, credits: e.target.value }))}
            required
          />
          <Textarea
            label="Reason / reference"
            hint="e.g. 'M-Pesa 100 KES received, code ABC123XYZ'"
            value={smsCredit.reason}
            onChange={(e) => setSmsCredit((c) => ({ ...c, reason: e.target.value }))}
            rows={2}
            required
          />
          {smsCreditError && <p className="text-xs text-secondary-300">{smsCreditError}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setIsCreditOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isCrediting}>
              Credit balance
            </Button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={isCorrectOpen} onClose={() => setIsCorrectOpen(false)} title="Correct data">
        <form onSubmit={handleCorrect} className="space-y-4">
          <Select
            label="Entity type"
            value={correction.entity_type}
            onChange={(e) => setCorrection((c) => ({ ...c, entity_type: e.target.value }))}
            options={CORRECTION_ENTITY_TYPES}
            required
          />
          <Input
            label="Entity ID"
            type="number"
            value={correction.entity_id}
            onChange={(e) => setCorrection((c) => ({ ...c, entity_id: e.target.value }))}
            required
          />
          <Textarea
            label="Correction (JSON)"
            hint='Only a limited safe field set per entity is allowed, e.g. {"notes": "corrected typo"}'
            value={correction.correction_json}
            onChange={(e) => setCorrection((c) => ({ ...c, correction_json: e.target.value }))}
            rows={4}
            required
          />
          <Textarea
            label="Reason"
            value={correction.reason}
            onChange={(e) => setCorrection((c) => ({ ...c, reason: e.target.value }))}
            rows={2}
            required
          />
          {correctionError && <p className="text-xs text-secondary-300">{correctionError}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setIsCorrectOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isCorrecting}>
              Submit correction
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
