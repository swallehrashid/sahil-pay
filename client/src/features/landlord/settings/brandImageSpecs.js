/**
 * What a logo and a signature must be to survive the pipeline.
 *
 * These numbers are not arbitrary house style — each one is a property of what
 * server/services/storage_service.py actually does to the file, and of the size
 * the renderers draw it at. Getting them wrong is what makes an upload "work"
 * and then look like nothing appeared:
 *
 *   * EVERY brand image is re-encoded to JPEG (IMAGE_RULES["brand"]), and
 *     transparency is flattened onto WHITE before that happens. A white or
 *     very pale logo on a transparent background therefore becomes white on
 *     white — uploaded successfully, and invisible on every document.
 *   * It is downscaled to at most 600px wide and squeezed to ~80KB. Anything
 *     larger buys nothing; anything much smaller is upscaled by the renderer
 *     and looks soft on a printed receipt.
 *   * The renderers box it: reports draw the logo at max 160×56px
 *     (services/report_builder.py _REPORT_STYLE), receipts at max ~46px tall
 *     (services/receipt_layout.py page_css). A tall square logo is therefore
 *     squeezed into a short strip — a wide lockup is what fits.
 */

export const BRAND_IMAGE_SPECS = {
  logo: {
    label: "Logo",
    hint: "Appears on every receipt, statement and report.",
    accept: "image/png,image/jpeg,image/webp",
    formats: ["PNG", "JPG", "WebP"],
    maxBytes: 5 * 1024 * 1024,
    minWidth: 300,
    idealWidth: "600–1200px wide",
    // Drawn into a 160×56 box on reports, ~46px tall on receipts.
    minRatio: 1,
    maxRatio: 6,
    idealRatio: "between 2:1 and 4:1 (wide, not tall)",
    requirements: [
      "PNG, JPG or WebP — under 5 MB.",
      "Wide rather than tall: aim for 2:1 to 4:1. It is drawn into a 160×56px box on reports and about 46px tall on receipts, so a square or portrait logo comes out tiny.",
      "At least 300px wide; 600–1200px is ideal. It is resized down to 600px, so anything bigger is discarded.",
      "Transparency is flattened onto WHITE. A white or very pale logo will be invisible on the page — upload a dark or full-colour version.",
      "Trim empty margin from the image before uploading. Built-in padding is drawn as part of the logo and shrinks the visible mark.",
    ],
  },
  signature: {
    label: "Signature",
    hint: "Stamped above the signature line on receipts, statements and reports.",
    accept: "image/png,image/jpeg,image/webp",
    formats: ["PNG", "JPG", "WebP"],
    maxBytes: 5 * 1024 * 1024,
    minWidth: 300,
    idealWidth: "600–1200px wide",
    minRatio: 1.5,
    maxRatio: 8,
    idealRatio: "between 3:1 and 5:1 (a wide strip)",
    requirements: [
      "PNG, JPG or WebP — under 5 MB.",
      "A wide strip: aim for 3:1 to 5:1. It is drawn at up to 60px tall, so a tall image shrinks to nothing.",
      "At least 300px wide; 600–1200px is ideal.",
      "Dark ink. Transparency is flattened onto white, so a signature written in white or a very light colour disappears.",
      "Sign on plain white paper in a dark pen and crop tight to the ink — a photo of a whole page reduces the signature to a few pixels.",
      "Shadows and page lines survive the upload. Photograph it flat in even light, or scan it.",
    ],
  },
};

/**
 * Check a chosen file against the spec BEFORE it is uploaded.
 * Returns { errors: string[], warnings: string[] } — errors block the save,
 * warnings let it through but say what will look wrong.
 */
export function inspectBrandImage(file, kind) {
  const spec = BRAND_IMAGE_SPECS[kind];
  return new Promise((resolve) => {
    const errors = [];
    const warnings = [];

    if (!spec) return resolve({ errors, warnings });
    if (file.size > spec.maxBytes) {
      errors.push(`That file is ${(file.size / 1024 / 1024).toFixed(1)} MB. The limit is 5 MB.`);
    }
    const type = (file.type || "").toLowerCase();
    if (type && !spec.accept.split(",").includes(type)) {
      errors.push(`${spec.formats.join(", ")} only — that file is ${type || "an unknown type"}.`);
    }
    if (errors.length) return resolve({ errors, warnings });

    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const { naturalWidth: w, naturalHeight: h } = img;
      const ratio = h ? w / h : 0;

      if (w < spec.minWidth) {
        warnings.push(
          `Only ${w}px wide. Below ${spec.minWidth}px it will look soft in print — ${spec.idealWidth} is ideal.`
        );
      }
      if (ratio && ratio < spec.minRatio) {
        warnings.push(
          `This is ${w}×${h} — taller than it is wide. It gets drawn into a short, wide box, so it will come out small. Ideal is ${spec.idealRatio}.`
        );
      } else if (ratio > spec.maxRatio) {
        warnings.push(
          `This is ${w}×${h} — a very long, thin strip. It will be scaled down to fit the width and end up hard to read.`
        );
      }
      resolve({ errors, warnings });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve({ errors: ["That file could not be read as an image."], warnings });
    };
    img.src = url;
  });
}
