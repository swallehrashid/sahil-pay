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
    throw new Error(`Download failed (${response.status})`);
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

export default downloadFile;
