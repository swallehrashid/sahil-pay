import { useState } from "react";

// Shared pagination state for any list page: exposes { page, perPage } plus
// the `params` to spread into the RTK Query call (?page=&per_page=), and
// setters that reset to page 1 when the page size changes. Pairs with the
// <Pagination> component and toPaginationMeta().
export function usePagination(initialPerPage = 25) {
  const [page, setPage] = useState(1);
  const [perPage, setPerPageState] = useState(initialPerPage);

  const setPerPage = (n) => {
    setPerPageState(n);
    setPage(1); // a bigger/smaller page invalidates the current page index
  };

  // Reset to page 1 — call when filters change so results start from the top.
  const reset = () => setPage(1);

  return { page, perPage, setPage, setPerPage, reset, params: { page, per_page: perPage } };
}

export default usePagination;
