import { NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";
import PageHeader from "@/components/layout/PageHeader";
import { LANDLORD_ROUTES } from "@/config/routePaths";

/**
 * One home for owner money, with the two halves of the job as tabs.
 *
 * These were separate top-level pages called "Owner payouts" and "Payout runs",
 * which read as duplicates of each other — the names do not say which one you
 * want, and both list payouts. They are not duplicates; they are consecutive
 * steps:
 *
 *   Runs    — WORK OUT what each owner is owed for a period, from the rent
 *             actually collected, then generate and mark those payouts paid.
 *   Ledger  — the RECORD of every remittance, including money sent outside a
 *             run (a one-off advance, a correction, last year's arrears).
 *
 * Keeping them apart at the top level meant the answer to "have I paid this
 * owner?" lived on one page and "what do I owe them?" on another. Same tab
 * pattern as Settings, so the shell is already familiar.
 */

const SECTIONS = [
  { to: LANDLORD_ROUTES.payoutRuns, label: "Payout runs", end: true },
  { to: LANDLORD_ROUTES.payoutLedger, label: "Ledger" },
];

export default function PayoutsLayout() {
  return (
    <div>
      <PageHeader
        title="Owner payouts"
        subtitle="Work out what each owner is owed, then record what you sent"
      />
      <div className="no-scrollbar mb-6 flex gap-1 overflow-x-auto border-b border-white/10">
        {SECTIONS.map((section) => (
          <NavLink
            key={section.to}
            to={section.to}
            end={section.end}
            className={({ isActive }) =>
              clsx(
                "whitespace-nowrap px-4 py-3 text-sm font-medium transition-colors duration-200",
                isActive
                  ? "border-b-2 border-secondary text-white"
                  : "text-white/50 hover:text-white/80"
              )
            }
          >
            {section.label}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  );
}
