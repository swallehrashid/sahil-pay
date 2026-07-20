import { useSyncExternalStore } from "react";

function subscribe(query) {
  return (callback) => {
    const mediaQueryList = window.matchMedia(query);
    mediaQueryList.addEventListener("change", callback);
    return () => mediaQueryList.removeEventListener("change", callback);
  };
}

// Subscribes to a matchMedia query via useSyncExternalStore — no effect/setState
// indirection, so the value is always correct even if `query` changes between renders.
export function useMediaQuery(query) {
  return useSyncExternalStore(
    subscribe(query),
    () => window.matchMedia(query).matches,
    () => false
  );
}

// The breakpoint ResponsiveTable and layout components switch table -> card on.
export const useIsMobile = () => useMediaQuery("(max-width: 767px)");

export default useMediaQuery;

