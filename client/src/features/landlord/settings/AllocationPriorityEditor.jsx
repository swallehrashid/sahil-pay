import { useEffect, useState } from "react";
import { ChevronUp, ChevronDown, RotateCcw } from "lucide-react";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetAllocationPriorityQuery,
  useUpdateAllocationPriorityMutation,
} from "../chargeCategoryApiSlice";

// Drag-order (via up/down) of EVERY (category, subcategory) pair — the order an
// auto-allocated payment clears a tenant's charges. Self-contained: reads and writes
// the dedicated /settings/allocation-priority endpoint (allocation_priority_json).
const SUB_COLOR = { balance: "amber", deposit: "secondary", current: "emerald" };

export default function AllocationPriorityEditor() {
  const { data, isLoading } = useGetAllocationPriorityQuery();
  const [savePriority, { isLoading: isSaving }] = useUpdateAllocationPriorityMutation();

  const [order, setOrder] = useState([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data?.priority) {
      setOrder(data.priority);
      setDirty(false);
    }
  }, [data]);

  const move = (index, delta) => {
    const target = index + delta;
    if (target < 0 || target >= order.length) return;
    const next = [...order];
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next);
    setDirty(true);
  };

  const save = async () => {
    try {
      await savePriority(order.map((p) => p.key)).unwrap();
      toast("Allocation priority saved.", { type: "success" });
      setDirty(false);
    } catch (err) {
      toast(err?.data?.error || "Could not save priority.", { type: "error" });
    }
  };

  const resetToDefault = async () => {
    try {
      // Empty order → backend backfills the Kenya default (balances → deposits → currents).
      await savePriority([]).unwrap();
      toast("Reset to the default order.", { type: "success" });
      setDirty(false);
    } catch (err) {
      toast(err?.data?.error || "Could not reset.", { type: "error" });
    }
  };

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <p className="text-sm font-medium text-white/70">Auto-allocation priority</p>
        <button
          type="button"
          onClick={resetToDefault}
          className="inline-flex items-center gap-1 text-xs text-white/40 hover:text-white"
        >
          <RotateCcw className="h-3 w-3" /> Reset to default
        </button>
      </div>
      <p className="mb-3 text-xs text-white/40">
        When you auto-allocate a confirmed payment, it clears these in order — top first.
        Each category's Deposit, Balance and This-month charges are listed separately.
      </p>

      {isLoading ? (
        <p className="py-4 text-sm text-white/40">Loading…</p>
      ) : (
        <ul className="space-y-2">
          {order.map((p, i) => (
            <li key={p.key} className="flex items-center gap-3 rounded-xl bg-white/5 px-3 py-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary/20 text-xs font-semibold text-white">
                {i + 1}
              </span>
              <span className="flex-1 truncate text-sm text-white/80">{p.label}</span>
              <Badge color={SUB_COLOR[p.subcategory] || "white"}>{p.subcategory}</Badge>
              <div className="flex flex-col">
                <button type="button" onClick={() => move(i, -1)} disabled={i === 0}
                        className="text-white/40 hover:text-white disabled:opacity-20">
                  <ChevronUp className="h-4 w-4" />
                </button>
                <button type="button" onClick={() => move(i, 1)} disabled={i === order.length - 1}
                        className="text-white/40 hover:text-white disabled:opacity-20">
                  <ChevronDown className="h-4 w-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {dirty && (
        <div className="mt-3 flex justify-end">
          <Button type="button" size="sm" onClick={save} isLoading={isSaving}>
            Save order
          </Button>
        </div>
      )}
    </div>
  );
}
