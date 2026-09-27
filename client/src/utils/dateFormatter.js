const TIMEZONE = "Africa/Nairobi";

// The API stores every timestamp in UTC. One sent without an offset
// ("2026-09-27T07:00:00") would otherwise be read in the DEVICE's timezone — on a
// phone or laptop set to US time, a 10:00 action in Nairobi showed as 14:00.
const NAIVE_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export function parseApiDate(value) {
  if (typeof value === "string" && NAIVE_DATETIME.test(value)) return new Date(`${value}Z`);
  return new Date(value);
}

export function formatDate(value, options) {
  if (!value) return "—";
  const date = parseApiDate(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-KE", {
    timeZone: TIMEZONE,
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...options,
  }).format(date);
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = parseApiDate(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-KE", {
    timeZone: TIMEZONE,
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  }).format(date);
}

// Shapes any date-ish value into the yyyy-mm-dd string <input type="date"> expects.
export function toInputDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

export function monthLabel(yyyyMm) {
  if (!yyyyMm) return "—";
  const [year, month] = yyyyMm.split("-");
  const date = new Date(Number(year), Number(month) - 1, 1);
  return new Intl.DateTimeFormat("en-KE", { month: "long", year: "numeric" }).format(date);
}

export function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

export default { parseApiDate, formatDate, formatDateTime, toInputDate, monthLabel, currentMonth };
