import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { RotateCcw, Save, Eye } from "lucide-react";
import Button from "@/components/ui/Button";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Spinner from "@/components/ui/Spinner";
import { toast } from "@/components/ui/Toast";
import { env } from "@/config/env";
import { getAccessToken } from "@/utils/tokenStorage";

/**
 * Design the receipt you actually print.
 *
 * Landlords print on whatever they have — a thermal roll at the gate, three
 * slips down an A4 sheet, or the full page. Rather than free-form design (which
 * mostly produces broken documents), the choices are: paper size, which of the
 * three header components sits left/centre/right, how tight the spacing is, and
 * which sections print. The live preview is a real PDF from the real renderer,
 * so what is shown is what comes out of the printer.
 */

const SLOT_LABELS = { left: "Left", center: "Centre", right: "Right" };
const SECTION_LABELS = {
  deposits: "Deposits held",
  balance: "Balance remaining",
  notes: "Thank-you note",
  signature: "Signature line",
};

async function api(path, options = {}) {
  const res = await fetch(`${env.apiBaseUrl}${path}`, {
    headers: {
      Authorization: `Bearer ${getAccessToken()}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    ...options,
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.error || "Something went wrong.");
  }
  return res;
}

export default function ReceiptLayoutSettings() {
  const [layout, setLayout] = useState(null);
  const [options, setOptions] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await api("/settings/receipt-layout");
        const data = await res.json();
        setLayout(data.layout);
        setOptions(data.options);
      } catch (err) {
        toast(err.message, { type: "error" });
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Revoke the old blob when a new preview replaces it, so a long editing
  // session doesn't accumulate PDFs in memory.
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const paperSpec = useMemo(
    () => options?.papers.find((p) => p.key === layout?.paper),
    [options, layout]
  );

  function set(patch) {
    setLayout((current) => ({ ...current, ...patch }));
  }

  function setSlot(slot, component) {
    setLayout((current) => {
      const slots = { ...current.header_slots };
      // A component lives in one slot only — if it's already elsewhere, move it
      // rather than drawing it twice.
      for (const key of Object.keys(slots)) {
        if (slots[key] === component && key !== slot) slots[key] = null;
      }
      slots[slot] = component || null;
      return { ...current, header_slots: slots };
    });
  }

  async function preview() {
    setPreviewing(true);
    try {
      const res = await api("/settings/receipt-layout/preview", {
        method: "POST",
        body: JSON.stringify({ layout }),
      });
      const blob = await res.blob();
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (err) {
      toast(err.message, { type: "error" });
    } finally {
      setPreviewing(false);
    }
  }

  async function save() {
    setSaving(true);
    try {
      await api("/settings/receipt-layout", {
        method: "PUT",
        body: JSON.stringify({ layout }),
      });
      toast("Receipt layout saved. New receipts will use it.", { type: "success" });
    } catch (err) {
      toast(err.message, { type: "error" });
    } finally {
      setSaving(false);
    }
  }

  function resetToDefault() {
    if (options?.default) setLayout(structuredClone(options.default));
  }

  if (loading) return <Spinner className="mx-auto my-12" />;
  if (!layout || !options) return null;

  return (
    <div className="animate-fade-in-up space-y-6">
      <div>
        <h2 className="text-lg font-light tracking-wide text-white">Receipt layout</h2>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-white/50">
          Set up the receipt to match what you actually print on. This affects
          every receipt — downloaded, emailed, or opened from an SMS link.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_minmax(0,420px)]">
        {/* ---- Controls -------------------------------------------------- */}
        <div className="space-y-6">
          {/* Paper */}
          <section className="glass p-5">
            <h3 className="text-sm font-medium text-white">Paper</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {options.papers.map((paper) => {
                const selected = layout.paper === paper.key;
                // A thumbnail in the real proportions — the fastest way to see
                // that "A4 third" is a narrow slip, not a small page.
                const ratio = paper.height_mm
                  ? paper.width_mm / paper.height_mm
                  : paper.width_mm / 200;
                return (
                  <button
                    key={paper.key}
                    type="button"
                    onClick={() => set({ paper: paper.key })}
                    className={clsx(
                      "flex items-center gap-3 rounded-xl border p-3 text-left transition-all",
                      selected
                        ? "border-secondary/60 bg-secondary/10 ring-1 ring-secondary/40"
                        : "border-white/10 bg-white/[0.03] hover:border-white/25"
                    )}
                  >
                    <span
                      className={clsx(
                        "flex-shrink-0 rounded border",
                        selected ? "border-secondary/60 bg-secondary/20" : "border-white/25 bg-white/10"
                      )}
                      style={{ width: 34 * Math.min(ratio, 1.6), height: 34 / Math.max(ratio, 0.35) }}
                    />
                    <span className="min-w-0">
                      <span className="block text-sm text-white">{paper.label}</span>
                      <span className="block text-xs leading-snug text-white/45">
                        {paper.description}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Header arrangement */}
          <section className="glass p-5">
            <h3 className="text-sm font-medium text-white">Header</h3>
            <p className="mt-1 text-xs text-white/45">
              Choose what sits where across the top. Leave a slot empty to drop it.
            </p>

            {/* Live schematic — shows the arrangement without a round-trip. */}
            <div className="mt-3 grid grid-cols-3 gap-2 rounded-lg border border-dashed border-white/15 p-3">
              {["left", "center", "right"].map((slot) => (
                <div
                  key={slot}
                  className={clsx(
                    "rounded px-2 py-3 text-center text-[10px]",
                    layout.header_slots[slot]
                      ? "bg-white/10 text-white/70"
                      : "bg-white/[0.03] text-white/25"
                  )}
                >
                  {options.components.find((c) => c.key === layout.header_slots[slot])?.label ?? "—"}
                </div>
              ))}
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {["left", "center", "right"].map((slot) => (
                <Select
                  key={slot}
                  label={SLOT_LABELS[slot]}
                  value={layout.header_slots[slot] ?? ""}
                  onChange={(e) => setSlot(slot, e.target.value)}
                  options={[
                    { value: "", label: "— empty —" },
                    ...options.components.map((c) => ({ value: c.key, label: c.label })),
                  ]}
                />
              ))}
            </div>
          </section>

          {/* Spacing + sections */}
          <section className="glass p-5">
            <h3 className="text-sm font-medium text-white">Spacing &amp; sections</h3>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Select
                label="Density"
                value={layout.density}
                onChange={(e) => set({ density: e.target.value })}
                options={[
                  { value: "normal", label: "Normal" },
                  { value: "compact", label: "Compact — fits more on a slip" },
                ]}
              />
              <div>
                <label className="mb-1.5 block text-sm font-medium text-white/80">
                  Text size ({Math.round(layout.font_scale * 100)}%)
                </label>
                <input
                  type="range"
                  min="0.8"
                  max="1.25"
                  step="0.05"
                  value={layout.font_scale}
                  onChange={(e) => set({ font_scale: Number(e.target.value) })}
                  className="w-full accent-[color:var(--color-secondary,#b95f7b)]"
                />
              </div>
            </div>

            {/* A two-column grid: inline-flex checkboxes ran together into one
                unreadable line on a wide screen. */}
            <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
              {options.sections.map((section) => (
                <Checkbox
                  key={section}
                  label={SECTION_LABELS[section] ?? section}
                  checked={Boolean(layout.sections[section])}
                  onChange={(e) =>
                    set({ sections: { ...layout.sections, [section]: e.target.checked } })
                  }
                  className="w-full"
                />
              ))}
            </div>
          </section>

          <div className="flex flex-wrap gap-3">
            <Button onClick={save} isLoading={saving} leftIcon={<Save className="h-4 w-4" />}>
              Save layout
            </Button>
            <Button variant="ghost" onClick={preview} isLoading={previewing} leftIcon={<Eye className="h-4 w-4" />}>
              Update preview
            </Button>
            <Button variant="ghost" onClick={resetToDefault} leftIcon={<RotateCcw className="h-4 w-4" />}>
              Reset to default
            </Button>
          </div>
        </div>

        {/* ---- Preview ---------------------------------------------------- */}
        <div className="glass flex flex-col p-4">
          <div className="mb-3 flex items-baseline justify-between">
            <h3 className="text-sm font-medium text-white">Preview</h3>
            {paperSpec && (
              <span className="text-xs text-white/40">
                {paperSpec.width_mm}mm ×{" "}
                {paperSpec.height_mm ? `${paperSpec.height_mm}mm` : "continuous"}
              </span>
            )}
          </div>

          {previewUrl ? (
            <iframe
              title="Receipt preview"
              src={previewUrl}
              className="h-[560px] w-full rounded-lg border border-white/10 bg-white"
            />
          ) : (
            <div className="flex h-[560px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-white/15 text-center">
              <Eye className="h-6 w-6 text-white/25" />
              <p className="max-w-[220px] text-sm text-white/45">
                Press <strong className="text-white/70">Update preview</strong> to
                see a sample receipt in this layout.
              </p>
            </div>
          )}
          <p className="mt-3 text-xs leading-relaxed text-white/35">
            A sample with made-up figures — real receipts use the tenant's own
            payment.
          </p>
        </div>
      </div>
    </div>
  );
}
