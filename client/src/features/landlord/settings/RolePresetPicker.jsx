import clsx from "clsx";
import { Eye, Wrench, Calculator, ClipboardList, SlidersHorizontal, Check } from "lucide-react";
import { useGetTeamPresetsQuery } from "./teamApiSlice";
import Spinner from "@/components/ui/Spinner";

/**
 * One-click starting points when creating a team member.
 *
 * A property manager running 100 blocks creates one login per owner plus two
 * caretakers each — hand-ticking a 12-module × view/edit matrix that many times
 * is not a workflow anybody would survive. A preset fills the matrix in and the
 * landlord adjusts from there.
 *
 * Presets are a SHORTCUT, never a ceiling: after applying one, every module and
 * every property stays individually editable below. The definitions come from
 * the API (services/team_preset_service.py) so the two can't drift apart.
 */

const ICONS = {
  owner: Eye,
  caretaker: Wrench,
  accountant: Calculator,
  secretary: ClipboardList,
  custom: SlidersHorizontal,
};

export default function RolePresetPicker({ value, onChange, className }) {
  const { data: presets = [], isLoading } = useGetTeamPresetsQuery();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-white/50">
        <Spinner size="sm" /> Loading roles…
      </div>
    );
  }

  return (
    <div className={className}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <label className="text-sm font-medium text-white/80">Start from a role</label>
        <span className="text-xs text-white/40">
          You can change anything below afterwards
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {presets.map((preset) => {
          const Icon = ICONS[preset.key] ?? SlidersHorizontal;
          const selected = value === preset.key;
          const editCount = preset.permissions.filter((p) => p.can_edit).length;
          const viewCount = preset.permissions.filter((p) => !p.can_edit).length;

          return (
            <button
              key={preset.key}
              type="button"
              onClick={() => onChange(preset)}
              aria-pressed={selected}
              className={clsx(
                "group relative rounded-xl border p-4 text-left transition-all",
                selected
                  ? "border-secondary/60 bg-secondary/10 ring-1 ring-secondary/40"
                  : "border-white/10 bg-white/[0.03] hover:border-white/25 hover:bg-white/[0.06]"
              )}
            >
              {selected && (
                <span className="absolute right-3 top-3 rounded-full bg-secondary p-1">
                  <Check className="h-3 w-3 text-white" />
                </span>
              )}

              <Icon className={clsx("h-5 w-5", selected ? "text-secondary" : "text-white/50")} />
              <div className="mt-2.5 text-sm font-medium text-white">{preset.label}</div>
              <p className="mt-1 text-xs leading-relaxed text-white/50">
                {preset.description}
              </p>

              {preset.key !== "custom" && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {editCount > 0 && (
                    <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                      {editCount} can edit
                    </span>
                  )}
                  {viewCount > 0 && (
                    <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-medium text-white/60">
                      {viewCount} view only
                    </span>
                  )}
                  {preset.scope === "specific" && (
                    <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                      Specific properties
                    </span>
                  )}
                </div>
              )}
            </button>
          );
        })}
      </div>

      {value === "owner" && (
        <p className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200/90">
          An owner must be limited to their own properties — otherwise they can
          read the books of every other landlord you manage.
        </p>
      )}
    </div>
  );
}

/** The badge used in team member lists and detail headers. */
export function PresetBadge({ preset, className }) {
  if (!preset) return null;
  const Icon = ICONS[preset] ?? SlidersHorizontal;
  const COLORS = {
    owner: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    caretaker: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    accountant: "bg-violet-500/15 text-violet-300 border-violet-500/30",
    secretary: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    custom: "bg-white/10 text-white/60 border-white/20",
  };
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium capitalize",
        COLORS[preset] ?? COLORS.custom,
        className
      )}
    >
      <Icon className="h-3 w-3" />
      {preset}
    </span>
  );
}
