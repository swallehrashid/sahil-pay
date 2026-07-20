import { useState } from "react";
import { FileText, FileSpreadsheet } from "lucide-react";
import Button from "./Button";
import { downloadFile } from "@/utils/downloadFile";
import { toast } from "./Toast";

// The reusable "Download PDF / Download Excel" pair used on every report/statement page.
// `endpoint` is the report path WITHOUT a format query string — this appends it.
export default function ExportButtons({ endpoint, filenameBase = "report", params = {} }) {
  const [loadingFormat, setLoadingFormat] = useState(null);

  const handleExport = async (format) => {
    setLoadingFormat(format);
    try {
      const query = new URLSearchParams({ ...params, format }).toString();
      await downloadFile(`${endpoint}?${query}`, {
        filename: `${filenameBase}.${format === "excel" ? "xlsx" : "pdf"}`,
        format,
      });
    } catch {
      toast("Export failed. Please try again.", { type: "error" });
    } finally {
      setLoadingFormat(null);
    }
  };

  return (
    <div className="flex flex-wrap gap-3">
      <Button
        variant="ghost"
        size="sm"
        leftIcon={<FileText className="h-4 w-4" />}
        isLoading={loadingFormat === "pdf"}
        onClick={() => handleExport("pdf")}
      >
        Download PDF
      </Button>
      <Button
        variant="ghost"
        size="sm"
        leftIcon={<FileSpreadsheet className="h-4 w-4" />}
        isLoading={loadingFormat === "excel"}
        onClick={() => handleExport("excel")}
      >
        Download Excel
      </Button>
    </div>
  );
}
