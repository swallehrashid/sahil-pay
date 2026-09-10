// Shapes RTK Query list responses into what <ResponsiveTable> / <Pagination> expect.
// Backend list endpoints return either a bare array or { items, total, page, per_page }.

export function toRows(response) {
  if (!response) return [];
  if (Array.isArray(response)) return response;
  if (Array.isArray(response.items)) return response.items;
  if (Array.isArray(response.results)) return response.results;
  if (Array.isArray(response.data)) return response.data;
  // The backend keys each list by its entity name — { properties: [...] },
  // { units: [...] }, { tenants: [...] }, etc. — not a generic `items`. Falling back
  // to the first array-valued property handles every one of those shapes, so list
  // tables stop rendering empty even though the API returned rows.
  return Object.values(response).find(Array.isArray) ?? [];
}

export function toPaginationMeta(response) {
  if (!response || Array.isArray(response)) {
    const length = Array.isArray(response) ? response.length : 0;
    return { total: length, page: 1, perPage: length };
  }
  return {
    total: response.total ?? 0,
    // The list endpoints return `current_page`, not `page` — reading only
    // `page` pinned this at 1 forever, so the pager showed "page 1" no matter
    // which page you were actually on.
    page: response.current_page ?? response.page ?? 1,
    perPage: response.per_page ?? response.perPage ?? 20,
  };
}

/**
 * Read a whole-dataset total out of a list response.
 *
 * WHY THIS EXISTS
 * ---------------
 * Every list endpoint returns its aggregates nested under `summary`:
 *
 *     { summary: { total_units: 1000, total_vacancies: 57 },
 *       units: [ ...20 rows... ], total: 1000, current_page: 1 }
 *
 * The pages read them FLAT — `data?.total_units` — which is always undefined,
 * so every card silently fell through to its fallback and counted the rows on
 * the current page instead. On an account with 100 properties and 1,000 units
 * the cards read 20 and 20: not a rounding problem, a different number
 * entirely, and one that looks plausible enough not to question.
 *
 * The fallback is kept for endpoints that genuinely have no summary block, but
 * it is now the exception rather than the thing that always runs.
 */
export function readSummary(response, key, fallback = 0) {
  const value = response?.summary?.[key] ?? response?.[key];
  return value ?? fallback;
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

export default { toRows, toPaginationMeta, readSummary, buildQueryParams };
