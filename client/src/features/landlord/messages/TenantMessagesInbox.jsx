import { useState, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { Send, MessageSquare, Plus } from "lucide-react";
import clsx from "clsx";
import Button from "@/components/ui/Button";
import Textarea from "@/components/ui/Textarea";
import Select from "@/components/ui/Select";
import Modal from "@/components/ui/Modal";
import Spinner from "@/components/ui/Spinner";
import EmptyState from "@/components/ui/EmptyState";
import { toast } from "@/components/ui/Toast";
import {
  useGetTenantMessageThreadsQuery,
  useGetTenantMessageThreadQuery,
  useReplyTenantMessageMutation,
} from "./tenantMessagesApiSlice";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { toRows } from "@/utils/tableAdapters";

// Landlord/team inbox for the tenant↔landlord conversation. Mounted at both
// /landlord/messages and /team/messages — the API scopes to the caller.
// Deep-linked from the notification bell via ?tenant=<id>.
function formatWhen(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export default function TenantMessagesInbox() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("tenant");

  const { data: threadsData, isLoading: threadsLoading } = useGetTenantMessageThreadsQuery(undefined, {
    pollingInterval: 20000,
  });
  const threads = threadsData?.threads ?? [];

  // Auto-select the first thread when none is chosen.
  useEffect(() => {
    if (!selectedId && threads.length > 0) {
      setSearchParams({ tenant: String(threads[0].tenant_id) }, { replace: true });
    }
  }, [selectedId, threads, setSearchParams]);

  const { data: threadData, isFetching: threadLoading } = useGetTenantMessageThreadQuery(selectedId, {
    skip: !selectedId,
    pollingInterval: 15000,
  });
  const [reply, { isLoading: isReplying }] = useReplyTenantMessageMutation();

  const [body, setBody] = useState("");
  const bottomRef = useRef(null);
  const messages = threadData?.messages ?? [];

  // #12 — landlord-initiated new conversation (pick any tenant, start a thread).
  const [isComposeOpen, setIsComposeOpen] = useState(false);
  const [composeTenant, setComposeTenant] = useState("");
  const [composeBody, setComposeBody] = useState("");
  const { data: tenantsData } = useGetTenantsQuery(undefined, { skip: !isComposeOpen });
  const allTenants = toRows(tenantsData);

  const handleCompose = async () => {
    if (!composeTenant || !composeBody.trim()) {
      toast("Pick a tenant and type a message.", { type: "error" });
      return;
    }
    try {
      await reply({ tenantId: composeTenant, body: composeBody.trim() }).unwrap();
      setIsComposeOpen(false);
      setSearchParams({ tenant: String(composeTenant) });
      setComposeTenant("");
      setComposeBody("");
    } catch (err) {
      toast(err?.data?.error || "Could not send the message.", { type: "error" });
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const selectThread = (id) => setSearchParams({ tenant: String(id) });

  const handleReply = async (e) => {
    e.preventDefault();
    if (!body.trim() || !selectedId) return;
    try {
      await reply({ tenantId: selectedId, body: body.trim() }).unwrap();
      setBody("");
    } catch (err) {
      const msg = err?.data?.error || "Could not send your reply.";
      toast(msg, { type: "error" });
    }
  };

  return (
    <div className="animate-fade-in-up space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-light tracking-wide text-white">Tenant messages</h1>
          <p className="text-sm text-white/50">In-app conversations with your tenants — start one or reply.</p>
        </div>
        <Button leftIcon={<Plus className="h-4 w-4" />} onClick={() => setIsComposeOpen(true)}>
          New message
        </Button>
      </div>

      <Modal isOpen={isComposeOpen} onClose={() => setIsComposeOpen(false)} title="New message">
        <div className="space-y-4">
          <Select
            label="Tenant"
            value={composeTenant}
            onChange={(e) => setComposeTenant(e.target.value)}
            options={allTenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
            required
          />
          <Textarea
            label="Message"
            value={composeBody}
            onChange={(e) => setComposeBody(e.target.value)}
            rows={4}
          />
          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={() => setIsComposeOpen(false)}>Cancel</Button>
            <Button leftIcon={<Send className="h-4 w-4" />} isLoading={isReplying} onClick={handleCompose}>
              Send
            </Button>
          </div>
        </div>
      </Modal>

      {threadsLoading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : threads.length === 0 ? (
        <EmptyState
          icon={<MessageSquare className="h-8 w-8" />}
          title="No tenant messages yet"
          description="Start a conversation with the New message button, or wait for a tenant to message you from their portal."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-[300px_1fr]">
          {/* Thread list */}
          <div className="glass max-h-[70vh] space-y-1 overflow-y-auto rounded-2xl p-2">
            {threads.map((t) => {
              const active = String(t.tenant_id) === String(selectedId);
              return (
                <button
                  key={t.tenant_id}
                  onClick={() => selectThread(t.tenant_id)}
                  className={clsx(
                    "w-full rounded-xl px-3 py-2.5 text-left transition-colors",
                    active ? "bg-secondary/20" : "hover:bg-white/5"
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-white">{t.tenant_name}</span>
                    {t.unread > 0 && (
                      <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-semibold text-white">
                        {t.unread}
                      </span>
                    )}
                  </div>
                  <p className="truncate text-xs text-white/50">
                    {t.unit_name ? `${t.unit_name} · ` : ""}{t.last_message}
                  </p>
                </button>
              );
            })}
          </div>

          {/* Conversation */}
          <div className="glass flex max-h-[70vh] flex-col rounded-2xl p-4 sm:p-6">
            {!selectedId ? (
              <p className="py-16 text-center text-sm text-white/50">Select a conversation.</p>
            ) : (
              <>
                {threadData?.tenant && (
                  <div className="mb-3 border-b border-white/10 pb-3">
                    <p className="text-sm font-medium text-white">{threadData.tenant.tenant_name}</p>
                    <p className="text-xs text-white/50">
                      {[threadData.tenant.unit_name, threadData.tenant.property_name].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                )}
                <div className="mb-4 flex-1 space-y-3 overflow-y-auto pr-1">
                  {threadLoading && messages.length === 0 ? (
                    <div className="flex justify-center py-10"><Spinner /></div>
                  ) : (
                    messages.map((m) => {
                      const fromTenant = m.sender_role === "tenant";
                      return (
                        <div key={m.id} className={clsx("flex", fromTenant ? "justify-start" : "justify-end")}>
                          <div
                            className={clsx(
                              "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm",
                              fromTenant ? "bg-white/10 text-white/90" : "bg-secondary/25 text-white"
                            )}
                          >
                            <div className="mb-0.5 flex items-center gap-2 text-xs text-white/50">
                              <span className="font-medium text-white/70">{m.sender_name}</span>
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

                <form onSubmit={handleReply} className="space-y-2 border-t border-white/10 pt-3">
                  <Textarea
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    placeholder="Type your reply…"
                    rows={2}
                  />
                  <div className="flex justify-end">
                    <Button type="submit" leftIcon={<Send className="h-4 w-4" />} isLoading={isReplying} disabled={!body.trim()}>
                      Reply
                    </Button>
                  </div>
                </form>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
