import { forwardRef } from "react";
import { ChevronDown } from "lucide-react";
import clsx from "clsx";

const Select = forwardRef(function Select(
  { label, error, hint, options = [], placeholder = "Select…", className, id, required, ...props },
  ref
) {
  const selectId = id || props.name;
  // A controlled caller passes `value`; only fall back to an uncontrolled
  // default when it doesn't — passing both triggers React's controlled/
  // uncontrolled warning and can desync the field.
  const isControlled = props.value !== undefined;
  return (
    <div className="w-full">
      {label && (
        <label htmlFor={selectId} className="mb-1.5 block text-sm font-medium text-white/70">
          {label} {required && <span className="text-secondary">*</span>}
        </label>
      )}
      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          {...(isControlled ? {} : { defaultValue: "" })}
          className={clsx("glass-input w-full appearance-none pr-10", error && "border-b-secondary", className)}
          {...props}
        >
          <option value="" disabled hidden>
            {placeholder}
          </option>
          {options.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-primary-900 text-white">
              {opt.label}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
      </div>
      {hint && !error && <p className="mt-1 text-xs text-white/40">{hint}</p>}
      {error && <p className="mt-1 text-xs text-secondary-300">{error}</p>}
    </div>
  );
});

export default Select;
