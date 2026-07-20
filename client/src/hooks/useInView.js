import { useEffect, useRef, useState } from "react";

// Fires when an element scrolls into view — the trigger for scroll-reveal
// animations on the marketing pages. Built to be fail-safe: content must always
// end up visible, even on an anchor jump or a fast flick that an
// IntersectionObserver alone can miss (a same-ratio jump past an element never
// produces an "intersecting" sample). Respects prefers-reduced-motion and
// environments without IntersectionObserver by revealing immediately.
export function useInView({ threshold = 0.15, rootMargin = "0px 0px -10% 0px" } = {}) {
  const ref = useRef(null);
  const [inView, setInView] = useState(() => {
    if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") return true;
    return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
  });

  useEffect(() => {
    if (inView) return undefined;
    const node = ref.current;
    if (!node) return undefined;

    // Already at/above the top of the viewport on mount (initial above-fold
    // content or an anchor jump) → reveal straight away.
    if (node.getBoundingClientRect().top < window.innerHeight) {
      setInView(true);
      return undefined;
    }

    const reveal = () => setInView(true);
    const observer = new IntersectionObserver(
      ([entry]) => {
        // Reveal when it enters view, or if it has already been scrolled past
        // (top above the viewport) — the fast-scroll safety net.
        if (entry.isIntersecting || entry.boundingClientRect.top < 0) {
          reveal();
          cleanup();
        }
      },
      { threshold, rootMargin }
    );
    // Backstop for fast flicks that skip the observer entirely.
    const onScroll = () => {
      if (node.getBoundingClientRect().top < window.innerHeight * 0.9) {
        reveal();
        cleanup();
      }
    };
    function cleanup() {
      observer.disconnect();
      window.removeEventListener("scroll", onScroll);
    }

    observer.observe(node);
    window.addEventListener("scroll", onScroll, { passive: true });
    return cleanup;
  }, [inView, threshold, rootMargin]);

  return [ref, inView];
}

export default useInView;
