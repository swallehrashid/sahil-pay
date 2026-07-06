import { forwardRef } from "react";
import clsx from "clsx";

const Input = forwardRef(function Input(
  { label, error, hint, leftIcon, rightIcon, className, id, required, ...props },
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
      <div className="relative flex items-center">
        {leftIcon && <span className="absolute left-3 text-white/40">{leftIcon}</span>}
        <input
          ref={ref}
          id={inputId}
          // #9 — number fields must never change on mouse-wheel scroll: blur on wheel.
          onWheel={props.type === "number" ? (e) => e.currentTarget.blur() : props.onWheel}
          className={clsx(
            "glass-input w-full",
            leftIcon && "pl-10",
            rightIcon && "pr-10",
            error && "border-b-secondary",
            className
          )}
          {...props}
        />
        {rightIcon && <span className="absolute right-3 text-white/40">{rightIcon}</span>}
      </div>
      {hint && !error && <p className="mt-1 text-xs text-white/40">{hint}</p>}
      {error && <p className="mt-1 text-xs text-secondary-300">{error}</p>}
    </div>
  );
});

export default Input;
