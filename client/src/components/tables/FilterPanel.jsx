import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { useIsMobile } from "@/hooks/useMediaQuery";
import Drawer from "@/components/ui/Drawer";
import Button from "@/components/ui/Button";

// Generic filter shell: pass filter inputs as children (date/property/unit/status/amount/
// source — whatever the page needs) so every page shares one layout and one mobile-Drawer
// collapse behavior instead of re-implementing it.
export default function FilterPanel({ children, onApply, onReset, title = "Filters" }) {
  const isMobile = useIsMobile();
  const [isOpen, setIsOpen] = useState(false);

  const body = (
    <div className="space-y-4">
      {children}
      <div className="flex gap-3 pt-2">
        <Button variant="primary" size="sm" className="flex-1" onClick={onApply}>
          Apply
        </Button>
        <Button variant="ghost" size="sm" className="flex-1" onClick={onReset}>
          Reset
        </Button>
      </div>
    </div>
  );

  if (isMobile) {
    return (
      <>
        <Button variant="ghost" size="sm" leftIcon={<SlidersHorizontal className="h-4 w-4" />} onClick={() => setIsOpen(true)}>
          {title}
        </Button>
        <Drawer isOpen={isOpen} onClose={() => setIsOpen(false)} title={title}>
          {body}
        </Drawer>
      </>
    );
  }

  return (
    <aside className="glass w-full max-w-xs flex-shrink-0 space-y-4 p-5">
      <h3 className="flex items-center gap-2 text-sm font-medium text-white">
        <SlidersHorizontal className="h-4 w-4" /> {title}
      </h3>
      {body}
    </aside>
  );
}
