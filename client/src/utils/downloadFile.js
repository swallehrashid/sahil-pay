import { env } from "@/config/env";
import { getAccessToken } from "./tokenStorage";

// Triggers a browser download for any report/export endpoint that returns a PDF/Excel/CSV blob.
// Used by <ExportButtons> and every "download" row-action across the app.
export async function downloadFile(path, { filename, format = "pdf" } = {}) {
  const url = path.startsWith("http") ? path : `${env.apiBaseUrl}${path}`;
  const token = getAccessToken();

  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });

  if (!response.ok) {
    // Surface the server's own reason ("not signed yet", "missing from storage")
    // instead of a bare status code the person cannot act on.
    let message = `Download failed (${response.status})`;
    try {
      const body = await response.json();
      message = body?.message || body?.error || message;
    } catch { /* not JSON */ }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename || `download.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

/**
 * Fetch an authenticated file and hand back an object URL to show it inline
 * (a scanned lease page in an <img>, a PDF in a new tab). The caller revokes it.
 */
export async function fetchObjectUrl(path) {
  const url = path.startsWith("http") ? path : `${env.apiBaseUrl}${path}`;
  const token = getAccessToken();
  const response = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : undefined });
  if (!response.ok) throw new Error(`Could not load file (${response.status})`);
  return URL.createObjectURL(await response.blob());
}

export default downloadFile;
