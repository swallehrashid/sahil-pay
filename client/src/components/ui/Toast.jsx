import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";
import clsx from "clsx";

let listeners = [];
let idCounter = 0;

// Imperative trigger — call toast("Saved!") from anywhere, no provider/context needed.
// eslint-disable-next-line react-refresh/only-export-components -- intentional: imperative API + viewport share one file by design
export function toast(message, { type = "success", duration = 4000 } = {}) {
  const id = ++idCounter;
  listeners.forEach((listener) => listener.add({ id, message, type, duration }));
  return id;
}

const ICONS = { success: CheckCircle2, error: AlertCircle, info: Info };
const COLORS = {
  success: "border-emerald-500/40 text-emerald-300",
  error: "border-secondary/50 text-secondary-200",
  info: "border-third/50 text-third-100",
};

// Mount <ToastViewport/> once near the app root (DashboardLayout / AuthLayout / PublicLayout).
export default function ToastViewport() {
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    const listener = { add: (t) => setToasts((prev) => [...prev, t]) };
    listeners.push(listener);
    return () => {
      listeners = listeners.filter((l) => l !== listener);
    };
  }, []);

  useEffect(() => {
    const timers = toasts.map((t) =>
      setTimeout(() => setToasts((prev) => prev.filter((item) => item.id !== t.id)), t.duration)
    );
    return () => timers.forEach(clearTimeout);
  }, [toasts]);

  const dismiss = (id) => setToasts((prev) => prev.filter((t) => t.id !== id));

  return createPortal(
    <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-3">
      {toasts.map((t) => {
        const Icon = ICONS[t.type] ?? Info;
        return (
          <div
            key={t.id}
            className={clsx(
              "glass-dark flex w-80 items-start gap-3 border p-4 animate-fade-in-up",
              COLORS[t.type] ?? COLORS.info
            )}
          >
            <Icon className="mt-0.5 h-5 w-5 flex-shrink-0" />
            <p className="flex-1 text-sm text-white/90">{t.message}</p>
            <button onClick={() => dismiss(t.id)} className="text-white/40 hover:text-white">
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>,
    document.body
  );
}
