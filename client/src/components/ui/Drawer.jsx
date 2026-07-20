import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

// Slide-over used for forms on mobile (FilterPanel, financial forms) instead of a centered Modal.
export default function Drawer({ isOpen, onClose, title, children, footer }) {
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e) => e.key === "Escape" && onClose?.();
    document.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 animate-fade-in bg-primary-950/70 backdrop-blur-sm" onClick={onClose} />
      <div className="glass-dark relative flex h-full w-full max-w-md animate-slide-over flex-col p-6">
        <div className="mb-4 flex items-center justify-between">
          {title && <h2 className="text-lg font-medium text-white">{title}</h2>}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-white/50 transition-colors hover:bg-white/10 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto pr-1">{children}</div>
        {footer && <div className="mt-6 flex justify-end gap-3">{footer}</div>}
      </div>
    </div>,
    document.body
  );
}
