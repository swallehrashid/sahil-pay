import { useEffect, useState } from "react";

// Debounces search/filter inputs before they hit the API (FilterPanel, table search boxes).
export function useDebounce(value, delay = 350) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timeout = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timeout);
  }, [value, delay]);

  return debounced;
}

export default useDebounce;
