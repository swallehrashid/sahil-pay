import { forwardRef } from "react";
import clsx from "clsx";

const Textarea = forwardRef(function Textarea(
  { label, error, hint, className, id, rows = 4, required, ...props },
  ref
) {
  const textareaId = id || props.name;
  return (
    <div className="w-full">
      {label && (
        <label htmlFor={textareaId} className="mb-1.5 block text-sm font-medium text-white/70">
          {label} {required && <span className="text-secondary">*</span>}
        </label>
      )}
      <textarea
        ref={ref}
        id={textareaId}
        rows={rows}
        className={clsx("glass-input w-full resize-none", error && "border-b-secondary", className)}
        {...props}
      />
      {hint && !error && <p className="mt-1 text-xs text-white/40">{hint}</p>}
      {error && <p className="mt-1 text-xs text-secondary-300">{error}</p>}
    </div>
  );
});

export default Textarea;
