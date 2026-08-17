import { Fragment } from "react";
import Checkbox from "@/components/ui/Checkbox";
import { PERMISSION_MODULES, PERMISSION_MODULE_LABELS } from "@/utils/constants";
import { useGetReportCatalogueQuery } from "./teamApiSlice";

// §4.20 — per-module View/Edit checkbox grid. can_edit=True forces can_view=True,
// and unchecking can_view clears can_edit (mirrors the backend's app-level rule).
//
// Reports get a second row of checkboxes underneath. View/Edit is too blunt for
// that module alone: it holds both a property statement an owner is entitled to
// and the payments report, arrears list and portfolio comparatives for the whole
// managed book. Without the finer grant, giving an owner their own statement
// meant handing over all of it.
export default function PermissionMatrix({ permissions, onChange }) {
  // Served from the backend so the list here can never offer a report the
  // routes do not gate, or miss one they do.
  const { data: catalogue } = useGetReportCatalogueQuery();
  const reports = catalogue?.reports ?? [];

  const update = (module, key, value) => {
    const next = { ...permissions, [module]: { ...permissions[module], [key]: value } };
    if (key === "can_edit" && value) next[module].can_view = true;
    if (key === "can_view" && !value) next[module].can_edit = false;
    onChange(next);
  };

  // null = every report. That is what an untouched member has, and it is NOT
  // the same as [] (none) — so the "All reports" box toggles between null and a
  // real list rather than between a full list and an empty one.
  const reportsEntry = permissions.reports ?? { can_view: false, can_edit: false };
  const allowed = reportsEntry.allowed_reports ?? null;
  const allReports = allowed === null;

  const setAllowed = (value) => {
    onChange({
      ...permissions,
      reports: { ...reportsEntry, allowed_reports: value },
    });
  };

  const toggleReport = (key, checked) => {
    const current = allowed ?? reports.map((r) => r.key);
    setAllowed(checked ? [...new Set([...current, key])] : current.filter((k) => k !== key));
  };

  return (
    <div className="glass overflow-hidden">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-white/40">
            <th className="px-4 py-3 font-medium">Module</th>
            <th className="px-4 py-3 font-medium">View</th>
            <th className="px-4 py-3 font-medium">Edit</th>
          </tr>
        </thead>
        <tbody>
          {PERMISSION_MODULES.map((module) => {
            const entry = permissions[module] ?? { can_view: false, can_edit: false };
            const [label, hint] = PERMISSION_MODULE_LABELS[module] ?? [module.replace(/_/g, " "), null];
            const showReportPicker =
              module === "reports" && (entry.can_view || entry.can_edit) && reports.length > 0;

            return (
              <Fragment key={module}>
                <tr className="border-b border-white/5 last:border-0">
                  {/* The bare module key does not tell a landlord what they are
                      handing over, and this grid is where that decision is made. */}
                  <td className="px-4 py-3 text-white/80">
                    <span className="block">{label}</span>
                    {hint && <span className="block text-xs text-white/40">{hint}</span>}
                  </td>
                  <td className="px-4 py-3">
                    <Checkbox checked={entry.can_view} onChange={(e) => update(module, "can_view", e.target.checked)} />
                  </td>
                  <td className="px-4 py-3">
                    <Checkbox checked={entry.can_edit} onChange={(e) => update(module, "can_edit", e.target.checked)} />
                  </td>
                </tr>

                {/* Only rendered once Reports is actually granted — an
                    unreachable list of report checkboxes reads as a bug. */}
                {showReportPicker && (
                  <tr className="border-b border-white/5 bg-white/[0.02]">
                    <td colSpan={3} className="px-4 pb-4 pt-1">
                      <p className="mb-2 pl-4 text-xs text-white/40">
                        Which reports? An owner usually needs only their property
                        statement.
                      </p>
                      <div className="pl-4">
                        <Checkbox
                          label="All reports (including any added later)"
                          checked={allReports}
                          onChange={(e) =>
                            setAllowed(e.target.checked ? null : [])
                          }
                        />
                      </div>
                      {!allReports && (
                        <div className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 pl-8 sm:grid-cols-2">
                          {reports.map((report) => (
                            <Checkbox
                              key={report.key}
                              label={report.label}
                              checked={(allowed ?? []).includes(report.key)}
                              onChange={(e) => toggleReport(report.key, e.target.checked)}
                            />
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
