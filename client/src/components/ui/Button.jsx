import { forwardRef } from "react";
import clsx from "clsx";
import Spinner from "./Spinner";

const VARIANTS = {
  primary: "btn-primary",
  ghost: "btn-ghost",
  danger:
    "inline-flex items-center justify-center gap-2 bg-secondary-700 text-white rounded-xl px-6 py-3 font-medium transition-all duration-300 hover:-translate-y-1 hover:shadow-lg hover:shadow-secondary-700/50 disabled:opacity-50 disabled:pointer-events-none disabled:hover:translate-y-0",
  subtle:
    "inline-flex items-center justify-center gap-2 bg-white/5 text-white/80 rounded-xl px-4 py-2 transition-all duration-300 hover:bg-white/10 disabled:opacity-50 disabled:pointer-events-none",
};

const SIZES = {
  sm: "text-sm px-4 py-2",
  md: "",
  lg: "text-lg px-8 py-4",
};

const Button = forwardRef(function Button(
  {
    variant = "primary",
    size = "md",
    isLoading = false,
    leftIcon,
    rightIcon,
    className,
    children,
    disabled,
    type = "button",
    ...props
  },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || isLoading}
      className={clsx(VARIANTS[variant], SIZES[size], className)}
      {...props}
    >
      {isLoading ? <Spinner size="sm" /> : leftIcon}
      <span>{children}</span>
      {!isLoading && rightIcon}
    </button>
  );
});

export default Button;
