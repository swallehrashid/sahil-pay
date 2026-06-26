import { useState } from "react";
import Modal from "@/components/ui/Modal";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useUploadBankStatementMutation } from "./paymentApiSlice";

// Uploads a statement file -> bank_statement_uploads, queued for async parsing (Celery).
export default function BankStatementUpload({ isOpen, onClose, onUploaded }) {
  const [uploadStatement, { isLoading }] = useUploadBankStatementMutation();
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) {
      setError("Select a statement file to upload");
      return;
    }
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const result = await uploadStatement(formData).unwrap();
      toast("Statement uploaded — parsing in the background.", { type: "success" });
      onUploaded?.(result?.id);
      setFile(null);
      onClose();
    } catch {
      toast("Could not upload the statement.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Upload bank statement">
      <form onSubmit={handleSubmit} className="space-y-4">
        <FileUpload label="Statement file" accept=".csv,.xlsx,.pdf" value={file} onChange={setFile} hint="CSV, Excel or PDF" />
        {error && <p className="text-xs text-secondary-300">{error}</p>}
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Upload &amp; parse
          </Button>
        </div>
      </form>
    </Modal>
  );
}
