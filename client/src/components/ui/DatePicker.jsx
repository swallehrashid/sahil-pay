import { forwardRef } from "react";
import { Calendar } from "lucide-react";
import clsx from "clsx";

const DatePicker = forwardRef(function DatePicker(
  { label, error, hint, className, id, required, ...props },
  ref
) {
  const inputId = id || props.name;
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
