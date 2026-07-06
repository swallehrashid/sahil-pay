import { useState, useRef, useEffect } from "react";
import { Send } from "lucide-react";
import clsx from "clsx";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import { toast } from "@/components/ui/Toast";
import { useGetPortalMessagesQuery, useSendPortalMessageMutation } from "./tenantPortalApiSlice";

// A conversation between the tenant and their landlord/team. The tenant raises
// what they want (tagged with a topic); the landlord and any team member with
// the `messages` permission reply, and those replies land here + in the bell.
function formatWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function TenantMessages() {
  const { data, isLoading } = useGetPortalMessagesQuery(undefined, { pollingInterval: 20000 });
  const [sendMessage, { isLoading: isSending }] = useSendPortalMessageMutation();

  const [body, setBody] = useState("");
  const [category, setCategory] = useState("general");
  const bottomRef = useRef(null);

  const messages = data?.messages ?? [];
  const categories = data?.categories ?? ["general"];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!body.trim()) return;
    try {
      await sendMessage({ body: body.trim(), category }).unwrap();
      setBody("");
      toast("Message sent to your landlord.", { type: "success" });
    } catch {
      toast("Could not send your message.", { type: "error" });
    }
  };

  return (
    <div className="animate-fade-in-up space-y-6">
      <div>
        <h1 className="text-2xl font-light tracking-wide text-white">Messages</h1>
        <p className="text-sm text-white/50">Talk directly to your landlord and property team.</p>
      </div>

      <div className="glass rounded-2xl p-4 sm:p-6">
        <div className="mb-4 max-h-[52vh] min-h-[220px] space-y-3 overflow-y-auto pr-1">
          {isLoading ? (
            <div className="flex justify-center py-10"><Spinner /></div>
          ) : messages.length === 0 ? (
            <p className="py-10 text-center text-sm text-white/50">
              No messages yet. Send your landlord a message below — questions about rent, repairs,
              documents, or anything else.
            </p>
          ) : (
            messages.map((m) => {
              const mine = m.sender_role === "tenant";
              return (
                <div key={m.id} className={clsx("flex", mine ? "justify-end" : "justify-start")}>
                  <div
                    className={clsx(
                      "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm",
                      mine ? "bg-secondary/25 text-white" : "bg-white/10 text-white/90"
                    )}
                  >
                    <div className="mb-0.5 flex items-center gap-2 text-xs text-white/50">
                      <span className="font-medium text-white/70">{mine ? "You" : m.sender_name}</span>
                      {m.category && (
                        <span className="rounded-full bg-white/10 px-2 py-0.5 capitalize">{m.category}</span>
                      )}
                      <span>{formatWhen(m.created_at)}</span>
                    </div>
                    <p className="whitespace-pre-wrap break-words">{m.body}</p>
                  </div>
                </div>
              );
            })
          )}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={handleSend} className="space-y-3 border-t border-white/10 pt-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="sm:w-48">
              <Select
                label="Topic"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                options={categories.map((c) => ({ value: c, label: c.charAt(0).toUpperCase() + c.slice(1) }))}
              />
            </div>
            <div className="flex-1">
              <Textarea
                label="Message"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Type your message to the landlord…"
                rows={2}
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button type="submit" leftIcon={<Send className="h-4 w-4" />} isLoading={isSending} disabled={!body.trim()}>
              Send
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
