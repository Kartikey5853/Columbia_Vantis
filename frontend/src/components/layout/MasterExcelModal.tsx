import React, { useState, useEffect } from "react";
import { X, Upload, FileSpreadsheet, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react";
import uploadService from "../../services/uploadService";
import { MasterDataStatus } from "../../types";

interface MasterExcelModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export const MasterExcelModal: React.FC<MasterExcelModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [status, setStatus] = useState<MasterDataStatus | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadStatus();
      setError(null);
      setSuccessMessage(null);
      setSelectedFile(null);
      setUploadProgress(0);
    }
  }, [isOpen]);

  const loadStatus = async () => {
    try {
      const data = await uploadService.getMasterDataStatus();
      setStatus(data);
    } catch {
      // Ignore
    }
  };

  if (!isOpen) return null;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.name.endsWith(".xlsx") && !file.name.endsWith(".xls")) {
        setError("Only Excel spreadsheets (.xlsx, .xls) are allowed.");
        return;
      }
      setSelectedFile(file);
      setError(null);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadProgress(10);
    setError(null);
    setSuccessMessage(null);

    try {
      const result = await uploadService.uploadMasterExcel(selectedFile, (pct) => {
        setUploadProgress(pct);
      });

      setSuccessMessage(result.message || "Master Excel file successfully processed and integrated.");
      await loadStatus();
      if (onSuccess) onSuccess();
    } catch (err: any) {
      setError(err.message || "Failed to process Master Excel catalogue.");
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-lg overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center border border-emerald-100">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-900">Master Excel Catalogue</h3>
              <p className="text-xs text-slate-500">Configure corporate master product dataset</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-5">
          {/* Status block */}
          <div className="p-4 rounded-xl bg-sky-50/60 border border-sky-100 flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-sky-100 text-sky-600 flex items-center justify-center shrink-0 mt-0.5">
              <RefreshCw className="w-4 h-4" />
            </div>
            <div className="text-sm">
              <div className="font-medium text-slate-800">
                {status?.is_configured ? "Master Catalogue Loaded" : "Using Live Cross-Platform Index"}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                {status?.is_configured
                  ? `File: ${status.details.filename} (${status.details.record_count} items) • Updated: ${status.details.last_updated?.slice(0, 10)}`
                  : `Currently indexing 20,577 records from scrapers & 21,382 canonical products in database.`}
              </div>
            </div>
          </div>

          {/* Upload Area */}
          <div className="border-2 border-dashed border-slate-200 rounded-xl p-6 text-center hover:border-sky-400 transition-colors bg-slate-50/30">
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={handleFileChange}
              className="hidden"
              id="master-excel-input"
              disabled={isUploading}
            />
            <label htmlFor="master-excel-input" className="cursor-pointer block space-y-2">
              <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-500 mx-auto flex items-center justify-center">
                <Upload className="w-6 h-6 text-sky-500" />
              </div>
              <div className="text-sm font-medium text-slate-700">
                {selectedFile ? selectedFile.name : "Choose an Excel file (.xlsx or .xls)"}
              </div>
              <p className="text-xs text-slate-400">
                {selectedFile
                  ? `${(selectedFile.size / 1024).toFixed(1)} KB`
                  : "Drag and drop or click to select replacement file"}
              </p>
            </label>
          </div>

          {/* Progress bar */}
          {isUploading && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-slate-500">
                <span>Processing & Validating Records...</span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                <div
                  className="bg-sky-500 h-full rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          )}

          {/* Messages */}
          {error && (
            <div className="p-3 rounded-lg bg-rose-50 border border-rose-100 text-rose-700 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {successMessage && (
            <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-100 text-emerald-700 text-xs flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{successMessage}</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-slate-50 border-t border-slate-100 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-200 transition-colors font-medium"
          >
            Close
          </button>
          <button
            type="button"
            onClick={handleUpload}
            disabled={!selectedFile || isUploading}
            className="px-5 py-2 rounded-lg text-sm text-white bg-sky-500 hover:bg-sky-600 disabled:opacity-50 transition-colors font-medium shadow-xs"
          >
            {isUploading ? "Uploading..." : "Upload & Ingest"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default MasterExcelModal;
