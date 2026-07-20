import clsx from "clsx";
import { useInView } from "@/hooks/useInView";

// Wraps any block so it fades + rises into place the first time it enters the
// viewport. `delay` staggers siblings; `as` lets it be a <li>, <div>, etc.
export default function Reveal({ children, className, delay = 0, as: Tag = "div" }) {
  const [ref, inView] = useInView();
  return (
    <Tag
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={clsx(
        "transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] will-change-transform",
        inView ? "translate-y-0 opacity-100 blur-0" : "translate-y-8 opacity-0 blur-[2px]",
        className
      )}
    >
      {children}
    </Tag>
  );
}
