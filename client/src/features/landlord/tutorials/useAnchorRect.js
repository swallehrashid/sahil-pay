import { useEffect, useRef, useState } from "react";

const POLL_INTERVAL_MS = 150;
const TIMEOUT_MS = 3000;

function isVisible(el) {
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function findAnchorElement(anchorId) {
  const matches = document.querySelectorAll(`[data-tour="${anchorId}"]`);
  for (const el of matches) {
    if (isVisible(el)) return el;
  }
  return null;
}

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

// Polls for a visible [data-tour="<anchorId>"] element for up to 3s (ONBOARDING_TUTORIALS_SPEC.md
// §5.2 rule 2/3) — lazy routes and data fetches mean the target often isn't in the DOM the
// instant a step navigates. Resolves to { rect, status } where status is 'pending' | 'resolved'
// | 'missing'. A 'missing' result is the non-negotiable fail-safe: the caller renders a centered
// card instead of a blank overlay.
export function useAnchorRect(anchorId) {
  const [rect, setRect] = useState(null);
  const [status, setStatus] = useState(anchorId ? "pending" : "missing");
  const elRef = useRef(null);

  useEffect(() => {
    if (!anchorId) {
      // Resetting for a new (absent) subscription target — not state derivable from props during render.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStatus("missing");
      setRect(null);
      elRef.current = null;
      return;
    }

    let cancelled = false;
    let pollTimer = null;
    let timeoutTimer = null;

    // Resetting for the new anchorId subscription target before polling starts.
    setStatus("pending");
    setRect(null);

    const measure = () => {
      const el = elRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    };

    const poll = () => {
      if (cancelled) return;
      const el = findAnchorElement(anchorId);
      if (el) {
        elRef.current = el;
        measure();
        setStatus("resolved");
        el.scrollIntoView({
          block: "center",
          behavior: prefersReducedMotion() ? "auto" : "smooth",
        });
        return;
      }
      pollTimer = window.setTimeout(poll, POLL_INTERVAL_MS);
    };

    poll();
    timeoutTimer = window.setTimeout(() => {
      if (cancelled) return;
      if (!elRef.current) {
        console.warn(`[tour] anchor missing: ${anchorId}`);
        setStatus("missing");
      }
    }, TIMEOUT_MS);

    let raf = null;
    const onViewportChange = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = null;
        measure();
      });
    };
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);

    // A resolved anchor can be removed from the DOM later (e.g. a modal it lived in closes) —
    // without this, the overlay would keep highlighting a stale, detached rect (§5.2 rule 3's
    // fail-safe has to hold for the whole step, not just the initial resolution). Re-resolve
    // whenever that happens, going back through the same poll/timeout path.
    const watchdog = window.setInterval(() => {
      if (cancelled) return;
      const el = elRef.current;
      if (el && (!el.isConnected || !isVisible(el))) {
        elRef.current = null;
        setRect(null);
        setStatus("pending");
        poll();
        timeoutTimer = window.setTimeout(() => {
          if (cancelled) return;
          if (!elRef.current) {
            console.warn(`[tour] anchor missing: ${anchorId}`);
            setStatus("missing");
          }
        }, TIMEOUT_MS);
      }
    }, 300);

    return () => {
      cancelled = true;
      elRef.current = null;
      if (pollTimer) window.clearTimeout(pollTimer);
      if (timeoutTimer) window.clearTimeout(timeoutTimer);
      if (raf) window.cancelAnimationFrame(raf);
      window.clearInterval(watchdog);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [anchorId]);

  return { rect, status };
}

export default useAnchorRect;
