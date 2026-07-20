import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useLocation } from "react-router-dom";
import { X } from "lucide-react";
import clsx from "clsx";
import Button from "@/components/ui/Button";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { useAnchorRect } from "./useAnchorRect";

const PAD = 8;
const CARD_WIDTH = 360;

// Computes a card position near `rect`, flipping side if the preferred placement doesn't fit.
function computeCardPosition(rect, placement = "bottom") {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const margin = 12;
  const cutout = {
    top: rect.top - PAD,
    left: rect.left - PAD,
    width: rect.width + PAD * 2,
    height: rect.height + PAD * 2,
  };

  const order = [placement, "bottom", "top", "right", "left"];
  for (const side of order) {
    if (side === "bottom" && cutout.top + cutout.height + 200 < vh) {
      return { top: cutout.top + cutout.height + margin, left: clampLeft(cutout.left, vw) };
    }
    if (side === "top" && cutout.top - 200 > 0) {
      return { bottom: vh - cutout.top + margin, left: clampLeft(cutout.left, vw) };
    }
    if (side === "right" && cutout.left + cutout.width + CARD_WIDTH + margin < vw) {
      return { top: clampTop(cutout.top, vh), left: cutout.left + cutout.width + margin };
    }
    if (side === "left" && cutout.left - CARD_WIDTH - margin > 0) {
      return { top: clampTop(cutout.top, vh), left: cutout.left - CARD_WIDTH - margin };
    }
  }
  // Nothing fits cleanly — center it.
  return null;
}

function clampLeft(left, vw) {
  return Math.min(Math.max(left, 12), vw - CARD_WIDTH - 12);
}
function clampTop(top, vh) {
  return Math.min(Math.max(top, 12), vh - 220);
}

function Cutout({ rect }) {
  if (!rect) return null;
  const top = rect.top - PAD;
  const left = rect.left - PAD;
  const width = rect.width + PAD * 2;
  const height = rect.height + PAD * 2;
  return (
    <>
      <div className="fixed left-0 right-0 top-0 z-[100] bg-primary-950/70 backdrop-blur-sm" style={{ height: Math.max(top, 0) }} />
      <div className="fixed bottom-0 left-0 right-0 z-[100] bg-primary-950/70 backdrop-blur-sm" style={{ top: top + height }} />
      <div className="fixed left-0 z-[100] bg-primary-950/70 backdrop-blur-sm" style={{ top, height, width: Math.max(left, 0) }} />
      <div className="fixed right-0 z-[100] bg-primary-950/70 backdrop-blur-sm" style={{ top, height, left: left + width }} />
      <div
        className="pointer-events-none fixed z-[100] rounded-xl ring-2 ring-secondary shadow-glow transition-all duration-200"
        style={{ top, left, width, height }}
      />
    </>
  );
}

export default function TourOverlay({ tutorial, stepIndex, sequenceMeta, onNext, onBack, onExit }) {
  const navigate = useNavigate();
  const location = useLocation();
  const isMobile = useIsMobile();
  const cardRef = useRef(null);
  const [phase, setPhase] = useState("navigating"); // 'navigating' | 'ready'

  const step = tutorial.steps[stepIndex];
  const isLast = stepIndex === tutorial.steps.length - 1;
  const isFirst = stepIndex === 0;

  // Sidebar-anchored steps never work on mobile (sidebar is hidden behind the hamburger) —
  // fall back to a centered card with the mobile-adapted copy (§9).
  const anchorForcedOff = isMobile && step.anchor?.startsWith("sidebar-");
  const effectiveAnchor = anchorForcedOff ? null : step.anchor;

  useEffect(() => {
    if (step.route && location.pathname !== step.route) {
      navigate(step.route);
    }
    // Gates anchor resolution until this step's navigation has been kicked off — not state derivable from props.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPhase("ready");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepIndex, tutorial.id]);

  const { rect, status } = useAnchorRect(phase === "ready" ? effectiveAnchor : null);

  // Route guard (§10 rule 10) — if the user hard-navigates somewhere the tour didn't send
  // them, exit cleanly rather than leaving a stale overlay pointed at the wrong page.
  const expectedRoutes = useMemo(() => {
    const routes = new Set();
    if (step.route) routes.add(step.route);
    const next = tutorial.steps[stepIndex + 1];
    if (next?.route) routes.add(next.route);
    return routes;
  }, [step, tutorial, stepIndex]);

  useEffect(() => {
    if (phase !== "ready") return;
    if (expectedRoutes.size && !expectedRoutes.has(location.pathname)) {
      onExit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  useEffect(() => {
    cardRef.current?.focus();
  }, [stepIndex]);

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === "Escape") onExit();
      else if (e.key === "ArrowRight" && !isLast) onNext();
      else if (e.key === "ArrowLeft" && !isFirst) onBack();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onExit, onNext, onBack, isLast, isFirst]);

  // advanceOn: click — let the target's own click handler run first (opening a modal,
  // navigating, etc.), then advance on the next tick (§5.2 rule 8).
  useEffect(() => {
    if (status !== "resolved" || !step.advanceOn || step.advanceOn.event !== "click") return;
    const el = document.querySelector(`[data-tour="${effectiveAnchor}"]`);
    if (!el) return;
    const handler = () => window.setTimeout(() => onNext(), 0);
    el.addEventListener("click", handler);
    return () => el.removeEventListener("click", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, effectiveAnchor, stepIndex]);

  const showCentered = !effectiveAnchor || status === "missing";
  const body = anchorForcedOff && step.mobileBody ? step.mobileBody : step.body;

  const position = !showCentered && rect ? computeCardPosition(rect, step.placement) : null;

  const stepCounter = `Step ${stepIndex + 1} of ${tutorial.steps.length}`;
  const sequenceLine = sequenceMeta
    ? `Part ${sequenceMeta.sequencePos + 1} of ${sequenceMeta.sequenceLen} — ${tutorial.title}`
    : null;

  const card = (
    <div
      ref={cardRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-label={tutorial.title}
      className={clsx(
        "glass-dark z-[101] w-[360px] max-w-[calc(100vw-24px)] bg-primary-900/95 p-5 outline-none",
        isMobile
          ? "fixed inset-x-0 bottom-0 w-full max-w-full animate-slide-over rounded-b-none"
          : "fixed animate-fade-in"
      )}
      style={
        isMobile
          ? undefined
          : position
            ? position
            : { top: "50%", left: "50%", transform: "translate(-50%, -50%)" }
      }
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          {sequenceLine && <p className="mb-1 text-xs font-medium uppercase tracking-wide text-secondary-200">{sequenceLine}</p>}
          <p className="text-xs text-white/40">{stepCounter}</p>
        </div>
        <button type="button" onClick={onExit} className="rounded-lg p-1 text-white/50 transition-colors hover:bg-white/10 hover:text-white" aria-label="Exit tour">
          <X className="h-4 w-4" />
        </button>
      </div>
      <h3 className="mb-2 text-base font-medium text-white">{step.title}</h3>
      <p className="whitespace-pre-line text-sm text-white/70">{body}</p>
      <div className="mt-5 flex items-center justify-between gap-3">
        <Button variant="ghost" size="sm" onClick={onExit}>
          Exit tour
        </Button>
        <div className="flex gap-2">
          {!isFirst && (
            <Button variant="ghost" size="sm" onClick={onBack}>
              Back
            </Button>
          )}
          <Button size="sm" onClick={onNext}>
            {isLast ? "Done" : "Next"}
          </Button>
        </div>
      </div>
    </div>
  );

  return createPortal(
    <>
      {showCentered ? (
        <div className="fixed inset-0 z-[100] bg-primary-950/70 backdrop-blur-sm" onClick={onExit} />
      ) : (
        <Cutout rect={rect} />
      )}
      {card}
    </>,
    document.body
  );
}
