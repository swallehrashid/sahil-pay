import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import Tabs from "@/components/ui/Tabs";
import PenaltiesReport from "@/features/landlord/reports/PenaltiesReport";
import BatchPenaltyRun from "./BatchPenaltyRun";

/**
 * Penalties, in the two modes a manager actually uses them.
 *
 *   Charges  — what has already been raised, automatic and manual together,
 *              which is the reconciliation view.
 *   Run one  — charge a filtered set of tenants now.
 *
 * The standing per-property POLICY stays in Settings → Penalties: it is
 * configuration that applies itself forever, which is a different kind of
 * decision from "these twelve people, this month" and does not belong on the
 * same screen as a button that moves money today.
 */
export default function PenaltiesPage() {
  const [tab, setTab] = useState("charges");

  return (
    <div>
      <PageHeader
        title="Penalties"
        subtitle="Late-payment charges — what has been raised, and raising more"
      />
      <Tabs
        tabs={[
          { key: "charges", label: "Charges" },
          { key: "run", label: "Run a batch" },
        ]}
        activeKey={tab}
        onChange={setTab}
        className="mb-6"
      />
      {/* PenaltiesReport renders its own heading, so it is shown bare here and
          the shell's header carries the page title for both tabs. */}
      {tab === "charges" ? <PenaltiesReport embedded /> : <BatchPenaltyRun />}
    </div>
  );
}
