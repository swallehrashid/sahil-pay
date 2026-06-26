// Shapes RTK Query list responses into what <ResponsiveTable> / <Pagination> expect.
// Backend list endpoints return either a bare array or { items, total, page, per_page }.

export function toRows(response) {
  if (!response) return [];
  if (Array.isArray(response)) return response;
  return response.items ?? response.results ?? response.data ?? [];
}

export function toPaginationMeta(response) {
  if (!response || Array.isArray(response)) {
    const length = Array.isArray(response) ? response.length : 0;
    return { total: length, page: 1, perPage: length };
  }
  return {
    total: response.total ?? 0,
    page: response.page ?? 1,
    perPage: response.per_page ?? response.perPage ?? 20,
  };
}

// Builds a `?page=1&per_page=20&...` query string from a filters object, dropping
// empty/undefined values so RTK Query cache keys stay stable.
export function buildQueryParams(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.set(key, value);
  });
  return params.toString();
}

export default { toRows, toPaginationMeta, buildQueryParams };
