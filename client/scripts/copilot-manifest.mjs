/**
 * Refresh public/downloads/copilot.json after replacing the bundled APK.
 *
 *   node scripts/copilot-manifest.mjs 1.0.0 "First public release"
 *
 * The download page reads this for the version, size and checksum it shows,
 * and appends the checksum to the download URL so a new APK is never served
 * from a stale cache.
 */
import { createHash } from "node:crypto";
import { readFileSync, statSync, writeFileSync } from "node:fs";

const APK = new URL("../public/downloads/sahil-pay-copilot.apk", import.meta.url);
const OUT = new URL("../public/downloads/copilot.json", import.meta.url);
const [version = "1.0.0", notes = ""] = process.argv.slice(2);

const bytes = readFileSync(APK);
const manifest = {
  name: "Sahil Pay Co-pilot",
  version,
  notes,
  file: "/downloads/sahil-pay-copilot.apk",
  size_bytes: statSync(APK).size,
  sha256: createHash("sha256").update(bytes).digest("hex"),
  min_android: "7.0",
  updated_at: new Date().toISOString().slice(0, 10),
};
writeFileSync(OUT, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(manifest);
