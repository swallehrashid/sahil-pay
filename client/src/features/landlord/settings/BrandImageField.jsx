import { useEffect, useState } from "react";
import { AlertTriangle, Check, Info, X } from "lucide-react";
import FileUpload from "@/components/ui/FileUpload";
import { BRAND_IMAGE_SPECS, inspectBrandImage } from "./brandImageSpecs";

/**
 * A logo/signature picker that shows what is ACTUALLY stored on the server.
 *
 * The plain FileUpload could not tell you whether anything had been saved — it
 * only ever showed the file you had just picked. That is what made the broken
 * upload so hard to spot: the page said "Settings saved", the field looked
 * populated, and the image was never on the server at all. Rendering the stored
 * URL means an upload that did not happen is visible immediately.
 *
 * The checks run against the file before it is sent, because the failures worth
 * catching (a white logo that flattens to invisible, a tall logo squeezed into a
 * 56px-high box) all produce a *successful* upload that simply looks wrong on
 * the document — the server has no way to call those an error.
 */
export default function BrandImageField({ label, kind, currentUrl, value, onChange }) {
  const spec = BRAND_IMAGE_SPECS[kind];
  const [checks, setChecks] = useState({ errors: [], warnings: [] });
  const [previewUrl, setPreviewUrl] = useState(null);
  const [showRequirements, setShowRequirements] = useState(false);

  useEffect(() => {
    if (!value) {
      setChecks({ errors: [], warnings: [] });
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(value);
    setPreviewUrl(url);
    let cancelled = false;
    inspectBrandImage(value, kind).then((result) => {
      if (!cancelled) setChecks(result);
    });
    return () => {
      cancelled = true;
      URL.revokeObjectURL(url);
    };
  }, [value, kind]);

  const handleChange = (file) => {
    if (!file) {
      onChange(null);
      return;
    }
    onChange(file);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-white/70">{label ?? spec.label}</p>
        <button
          type="button"
          onClick={() => setShowRequirements((open) => !open)}
          className="flex items-center gap-1 text-xs text-secondary hover:text-secondary-200"
        >
          <Info className="h-3.5 w-3.5" />
          {showRequirements ? "Hide requirements" : "Requirements"}
        </button>
      </div>

      {showRequirements && (
        <ul className="space-y-1.5 rounded-lg bg-white/5 p-4 text-xs text-white/60">
          {spec.requirements.map((line) => (
            <li key={line} className="flex gap-2">
              <span className="text-secondary">•</span>
              <span>{line}</span>
            </li>
          ))}
        </ul>
      )}

      {/* What is on the server right now. Checkerboard behind it, because a
          logo that flattened to white is otherwise indistinguishable from an
          empty box on a dark page. */}
      {currentUrl && !value && (
        <div className="flex items-center gap-3 rounded-lg bg-white/5 p-3">
          <div
            className="flex h-14 w-32 items-center justify-center rounded bg-white p-1"
            style={{
              backgroundImage:
                "linear-gradient(45deg,#e5e5e5 25%,transparent 25%),linear-gradient(-45deg,#e5e5e5 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#e5e5e5 75%),linear-gradient(-45deg,transparent 75%,#e5e5e5 75%)",
              backgroundSize: "10px 10px",
              backgroundPosition: "0 0,0 5px,5px -5px,-5px 0",
            }}
          >
            <img src={currentUrl} alt={`current ${kind}`} className="max-h-12 max-w-full object-contain" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 text-xs text-emerald-300">
              <Check className="h-3.5 w-3.5" /> Saved — this is what appears on your documents.
            </p>
            <p className="mt-0.5 truncate text-xs text-white/35">{currentUrl}</p>
          </div>
        </div>
      )}

      {!currentUrl && !value && (
        <p className="text-xs text-white/40">
          No {kind} saved yet. {spec.hint}
        </p>
      )}

      {value && previewUrl && (
        <div className="flex items-center gap-3 rounded-lg bg-white/5 p-3">
          <div className="flex h-14 w-32 items-center justify-center rounded bg-white p-1">
            <img src={previewUrl} alt={`new ${kind}`} className="max-h-12 max-w-full object-contain" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs text-white/70">
              {value.name} — not saved yet. Press <strong>Save</strong> below.
            </p>
            <button
              type="button"
              onClick={() => handleChange(null)}
              className="mt-1 flex items-center gap-1 text-xs text-white/40 hover:text-secondary"
            >
              <X className="h-3 w-3" /> Remove
            </button>
          </div>
        </div>
      )}

      <FileUpload accept={spec.accept} value={value} onChange={handleChange} hint={spec.hint} />

      {checks.errors.map((message) => (
        <p key={message} className="flex items-start gap-1.5 text-xs text-secondary-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
          {message}
        </p>
      ))}
      {checks.warnings.map((message) => (
        <p key={message} className="flex items-start gap-1.5 text-xs text-amber-300/80">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
          {message}
        </p>
      ))}
    </div>
  );
}
