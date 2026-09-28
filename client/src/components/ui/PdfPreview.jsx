import { useEffect, useRef, useState } from "react";
import Spinner from "./Spinner";

/**
 * Draw a PDF's pages onto canvases — the actual file, not a browser plug-in.
 *
 * An <iframe> preview depends on the browser having a PDF viewer: phones do
 * not, headless browsers do not, and a preview that is blank on half the
 * devices cannot promise "what you see is what prints". This renders the
 * very bytes the printer will receive, page by page, at the page's real
 * proportions — an A4 sheet with the receipt in its top third looks exactly
 * like that.
 *
 * pdf.js is imported lazily so only the screens that preview a PDF pay for it.
 */
export default function PdfPreview({ url, className, "data-testid": testId }) {
  const holder = useRef(null);
  const [state, setState] = useState("loading");

  useEffect(() => {
    if (!url) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        // Bundled as a real Worker (a .js file) rather than a .mjs URL, so it
        // needs no special MIME type from the web server.
        const { default: PdfWorker } = await import("pdfjs-dist/build/pdf.worker.min.mjs?worker");
        if (!pdfjs.GlobalWorkerOptions.workerPort) pdfjs.GlobalWorkerOptions.workerPort = new PdfWorker();
        const doc = await pdfjs.getDocument(url).promise;
        const el = holder.current;
        if (cancelled || !el) return;
        el.innerHTML = "";
        const width = el.clientWidth || 380;
        for (let n = 1; n <= doc.numPages; n += 1) {
          const page = await doc.getPage(n);
          const base = page.getViewport({ scale: 1 });
          const ratio = window.devicePixelRatio || 1;
          const viewport = page.getViewport({ scale: (width / base.width) * ratio });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = `${width}px`;
          canvas.style.height = `${viewport.height / ratio}px`;
          canvas.className = "block bg-white shadow-lg";
          el.appendChild(canvas);
          await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
        }
        if (!cancelled) setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    })();
    return () => { cancelled = true; };
  }, [url]);

  return (
    <div className={className} data-testid={testId}>
      {state === "loading" && <Spinner className="mx-auto my-12" />}
      {state === "error" && (
        <p className="p-4 text-sm text-white/60">
          The preview could not be drawn here. <a className="text-secondary underline" href={url} target="_blank" rel="noreferrer">Open the PDF</a>.
        </p>
      )}
      <div ref={holder} className="space-y-3" />
    </div>
  );
}
