import { Inbox } from "lucide-react";

export default function EmptyState({ icon, title = "Nothing here yet", description, action }) {
  return (
    <div className="glass flex flex-col items-center justify-center gap-3 px-6 py-16 text-center animate-fade-in">
      <span className="rounded-full bg-white/10 p-4 text-white/40">{icon ?? <Inbox className="h-6 w-6" />}</span>
      <h3 className="text-base font-medium text-white">{title}</h3>
      {description && <p className="max-w-sm text-sm text-white/50">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
