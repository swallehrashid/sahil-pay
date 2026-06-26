import { useCallback, useMemo, useRef, useState } from "react";
import { UploadCloud, X, FileText } from "lucide-react";
import clsx from "clsx";

// Generic drag-drop uploader. Hands raw File objects back via onChange — the calling
// form wires the actual Cloudinary (images) / S3 (docs, receipts) request, since that
// differs per use case.
export default function FileUpload({ label, accept, multiple = false, hint, value, onChange, className }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const files = useMemo(() => (value ? (Array.isArray(value) ? value : [value]) : []), [value]);

  const handleFiles = useCallback(
    (fileList) => {
      const incoming = Array.from(fileList);
      if (!incoming.length) return;
      onChange?.(multiple ? [...files, ...incoming] : incoming[0]);
    },
    [multiple, onChange, files]
  );

  const removeFile = (index) => {
    if (!multiple) {
      onChange?.(null);
      return;
    }
    onChange?.(files.filter((_, i) => i !== index));
  };

  return (
    <div className={clsx("w-full", className)}>
      {label && <p className="mb-1.5 text-sm font-medium text-white/70">{label}</p>}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={clsx(
          "glass cursor-pointer border-dashed px-6 py-8 text-center transition-all duration-300",
          isDragging ? "border-secondary bg-secondary/10" : "hover:border-third/50"
        )}
      >
        <UploadCloud className="mx-auto mb-2 h-8 w-8 text-white/40" />
        <p className="text-sm text-white/70">
          Drag &amp; drop, or <span className="text-secondary">browse</span>
        </p>
        {hint && <p className="mt-1 text-xs text-white/40">{hint}</p>}
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-3 space-y-2">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="flex items-center justify-between gap-2 rounded-lg bg-white/5 px-3 py-2 text-sm text-white/80"
            >
              <span className="flex items-center gap-2 truncate">
                <FileText className="h-4 w-4 flex-shrink-0 text-white/40" />
                <span className="truncate">{file.name}</span>
              </span>
              <button
                type="button"
                onClick={() => removeFile(index)}
                className="text-white/40 transition-colors hover:text-secondary"
              >
                <X className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
