/**
 * The one search rule for every client-side filter in Sahil Pay (the server
 * side is services/search.py): split the query into words, and a row matches
 * when EVERY word appears somewhere in it, in any order.
 *
 * So "Alex Kirui", "kirui alex" and "alex kir" all find Alex Kirui, and typing
 * a space never ends the search. Matching the whole query as one string —
 * which is what every filter used to do — found nothing as soon as the words
 * came from two different fields.
 */
export function searchWords(query) {
  return String(query ?? "").trim().toLowerCase().split(/\s+/).filter(Boolean);
}

export function matchesAllWords(haystack, query) {
  const terms = searchWords(query);
  if (!terms.length) return true;
  const hay = (Array.isArray(haystack) ? haystack.filter(Boolean).join(" ") : String(haystack ?? "")).toLowerCase();
  return terms.every((t) => hay.includes(t));
}
