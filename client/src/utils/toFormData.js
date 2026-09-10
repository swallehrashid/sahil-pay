/**
 * Turn a form object into FormData — but only when it actually carries a file.
 *
 * WHY THIS EXISTS
 * ---------------
 * RTK Query's fetchBaseQuery JSON-stringifies any plain object body. A `File`
 * has no JSON representation, so `JSON.stringify({ logo: file })` yields
 * `{"logo":{}}` — the request succeeds, the server sees an empty object where a
 * file should be, and nothing anywhere reports a problem. That is exactly how
 * the company logo and signature uploads silently did nothing: the settings
 * page said "Settings saved", and the file never left the browser.
 *
 * FormData is the only body fetchBaseQuery passes through untouched (see
 * sanitizeBody in store/apiSlice.js), so a request carrying a file must be
 * FormData or it is not carrying the file.
 *
 * Returns null when there is no file, so callers keep the plain-JSON path for
 * ordinary saves. That matters: a multipart body arrives at Flask as
 * request.form, where EVERY value is a string — `false` becomes "false", which
 * is truthy. Only pay that cost when a file forces it.
 */

const isFile = (value) =>
  (typeof File !== "undefined" && value instanceof File) ||
  (typeof Blob !== "undefined" && value instanceof Blob);

export function hasFile(source) {
  return Object.values(source ?? {}).some(
    (value) => isFile(value) || (Array.isArray(value) && value.some(isFile))
  );
}

/**
 * @param {object} source  plain object, possibly containing File values
 * @returns {FormData|null} FormData when a file is present, else null
 */
export default function toFormData(source) {
  if (!hasFile(source)) return null;

  const data = new FormData();
  for (const [key, value] of Object.entries(source ?? {})) {
    if (value === undefined || value === null) continue;
    if (isFile(value)) {
      data.append(key, value, value.name);
    } else if (Array.isArray(value)) {
      value.forEach((item) =>
        isFile(item) ? data.append(key, item, item.name) : data.append(key, String(item))
      );
    } else if (typeof value === "object") {
      // Nested objects (allocation priority, receipt layout) have to survive the
      // trip as JSON — the server json.loads these fields back out of the form.
      data.append(key, JSON.stringify(value));
    } else {
      // Booleans included: "true"/"false" strings, which the server coerces.
      data.append(key, String(value));
    }
  }
  return data;
}
