import { forwardRef, useId } from "react";
import { Check } from "lucide-react";
import clsx from "clsx";

const Checkbox = forwardRef(function Checkbox({ label, className, id, ...props }, ref) {
  // useId() so a caller that passes neither id nor name still gets a label
  // bound to its input. Without it htmlFor and id were both undefined: the
  // label toggled nothing when clicked, and announced nothing to a screen
  // reader. Same fix Input already carries.
  const generatedId = useId();
  const checkboxId = id || props.name || generatedId;
  return (
    <label
      htmlFor={checkboxId}
      className={clsx("inline-flex select-none items-center gap-2 cursor-pointer", className)}
    >
      <span className="relative inline-flex h-5 w-5 items-center justify-center">
        <input ref={ref} id={checkboxId} type="checkbox" className="peer sr-only" {...props} />
        <span className="absolute inset-0 rounded-md border border-white/25 bg-white/5 transition-all duration-200 peer-checked:border-secondary peer-checked:bg-secondary peer-focus-visible:ring-2 peer-focus-visible:ring-secondary/50" />
        <Check className="relative z-10 h-3.5 w-3.5 text-white opacity-0 transition-opacity duration-150 peer-checked:opacity-100" />
      </span>
      {label && <span className="text-sm text-white/80">{label}</span>}
    </label>
  );
});

export default Checkbox;
