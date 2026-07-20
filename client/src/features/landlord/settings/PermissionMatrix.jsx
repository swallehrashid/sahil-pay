import Checkbox from "@/components/ui/Checkbox";
import { PERMISSION_MODULES } from "@/utils/constants";

// §4.20 — per-module View/Edit checkbox grid. can_edit=True forces can_view=True,
// and unchecking can_view clears can_edit (mirrors the backend's app-level rule).
export default function PermissionMatrix({ permissions, onChange }) {
  const update = (module, key, value) => {
    const next = { ...permissions, [module]: { ...permissions[module], [key]: value } };
    if (key === "can_edit" && value) next[module].can_view = true;
    if (key === "can_view" && !value) next[module].can_edit = false;
    onChange(next);
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
            return (
              <tr key={module} className="border-b border-white/5 last:border-0">
                <td className="px-4 py-3 capitalize text-white/80">{module.replace("_", " ")}</td>
                <td className="px-4 py-3">
                  <Checkbox checked={entry.can_view} onChange={(e) => update(module, "can_view", e.target.checked)} />
                </td>
                <td className="px-4 py-3">
                  <Checkbox checked={entry.can_edit} onChange={(e) => update(module, "can_edit", e.target.checked)} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
