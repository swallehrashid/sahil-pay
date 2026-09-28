import { forwardRef, useId } from "react";
import { Calendar } from "lucide-react";
import clsx from "clsx";

const DatePicker = forwardRef(function DatePicker(
  { label, error, hint, className, id, required, ...props },
  ref
) {
  // useId() so a label is always bound to its input — without it a picker
  // with neither id nor name had an unlabelled field (screen readers and
  // label-based lookups found nothing). Same fix as Checkbox and Input.
  const generatedId = useId();
  const inputId = id || props.name || generatedId;
  return (
    <div className="w-full">
      {label && (
        <label htmlFor={inputId} className="mb-1.5 block text-sm font-medium text-white/70">
          {label} {required && <span className="text-secondary">*</span>}
        </label>
      )}
      <div className="relative">
        <input
          ref={ref}
          id={inputId}
          type="date"
          className={clsx("glass-input w-full pr-10 [color-scheme:dark]", error && "border-b-secondary", className)}
          {...props}
        />
        <Calendar className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
      </div>
      {hint && !error && <p className="mt-1 text-xs text-white/40">{hint}</p>}
      {error && <p className="mt-1 text-xs text-secondary-300">{error}</p>}
    </div>
  );
});

export default DatePicker;
