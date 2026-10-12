import React, { useState } from "react";
import { X, Search, UploadCloud, Tag } from "lucide-react";

interface BulkSearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSearch: (identifiers: string[]) => void;
  initialChips?: string[];
  mode?: "paste" | "csv";
}

export const BulkSearchModal: React.FC<BulkSearchModalProps> = ({
  isOpen,
  onClose,
  onSearch,
  initialChips = [],
  mode = "paste",
}) => {
  const [chips, setChips] = useState<string[]>(initialChips);
  const [textInput, setTextInput] = useState("");
  const [activeTab, setActiveTab] = useState<"paste" | "csv">(mode);
  const [csvFileName, setCsvFileName] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleAddTokens = (text: string) => {
    const rawTokens = text.split(/[\s,\n\r\t]+/).map((t) => t.trim()).filter((t) => t.length > 2);
    const newChips = Array.from(new Set([...chips, ...rawTokens]));
    setChips(newChips);
    setTextInput("");
  };

  const removeChip = (index: number) => {
    setChips(chips.filter((_, i) => i !== index));
  };

  const handleCsvFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setCsvFileName(file.name);
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      if (content) {
        handleAddTokens(content);
      }
    };
    reader.readAsText(file);
  };

  const handleSubmit = () => {
    if (textInput.trim()) {
      const rawTokens = textInput.split(/[\s,\n\r\t]+/).map((t) => t.trim()).filter((t) => t.length > 2);
      const all = Array.from(new Set([...chips, ...rawTokens]));
      onSearch(all);
    } else {
      onSearch(chips);
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-lg overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header with Tabs */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setActiveTab("paste")}
              className={`text-sm font-semibold pb-1 border-b-2 transition-colors ${
                activeTab === "paste"
                  ? "border-sky-500 text-sky-600"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              Paste SKUs / EANs
            </button>
            <button
              onClick={() => setActiveTab("csv")}
              className={`text-sm font-semibold pb-1 border-b-2 transition-colors ${
                activeTab === "csv"
                  ? "border-sky-500 text-sky-600"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              Upload CSV Search
            </button>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-4">
          {activeTab === "paste" ? (
            <div className="space-y-3">
              <label className="text-xs font-semibold text-slate-700 block uppercase tracking-wider">
                Paste comma or newline separated identifiers:
              </label>
              <textarea
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                placeholder="e.g. 2005101, 1594731, 195981234567, WE8479..."
                rows={4}
                className="w-full text-sm p-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 font-mono text-slate-800"
              />
              <div className="flex justify-between items-center text-xs text-slate-400">
                <span>Separate by comma, space, or new line</span>
                <button
                  type="button"
                  onClick={() => handleAddTokens(textInput)}
                  disabled={!textInput.trim()}
                  className="px-2.5 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-md font-medium transition-colors disabled:opacity-40"
                >
                  Convert to Chips
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <label className="text-xs font-semibold text-slate-700 block uppercase tracking-wider">
                Select CSV with SKUs or EANs:
              </label>
              <div className="border-2 border-dashed border-slate-200 rounded-xl p-6 text-center hover:border-sky-400 transition-colors bg-slate-50/50">
                <input
                  type="file"
                  accept=".csv,.txt"
                  onChange={handleCsvFile}
                  className="hidden"
                  id="bulk-csv-input"
                />
                <label htmlFor="bulk-csv-input" className="cursor-pointer block space-y-2">
                  <UploadCloud className="w-8 h-8 text-sky-500 mx-auto" />
                  <div className="text-sm font-medium text-slate-700">
                    {csvFileName || "Upload CSV File for Bulk Search"}
                  </div>
                  <p className="text-xs text-slate-400">
                    Identifies columns containing SKUs, EANs, or Style Codes
                  </p>
                </label>
              </div>
            </div>
          )}

          {/* Chips list */}
          {chips.length > 0 && (
            <div className="space-y-1.5 pt-2 border-t border-slate-100">
              <div className="flex justify-between items-center text-xs text-slate-500 font-medium">
                <span>{chips.length} Identifiers Added:</span>
                <button
                  type="button"
                  onClick={() => setChips([])}
                  className="text-rose-600 hover:underline text-[11px]"
                >
                  Clear all
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto p-2 bg-slate-50 rounded-xl border border-slate-100">
                {chips.map((chip, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1.5 bg-white border border-slate-200 text-slate-800 text-xs px-2.5 py-1 rounded-full shadow-2xs font-mono"
                  >
                    <Tag className="w-3 h-3 text-sky-500" />
                    <span>{chip}</span>
                    <button
                      type="button"
                      onClick={() => removeChip(idx)}
                      className="text-slate-400 hover:text-rose-500 transition-colors"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
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
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={chips.length === 0 && !textInput.trim()}
            className="px-5 py-2 rounded-lg text-sm text-white bg-sky-500 hover:bg-sky-600 disabled:opacity-50 transition-colors font-medium shadow-xs inline-flex items-center gap-2"
          >
            <Search className="w-4 h-4" />
            <span>Search Products</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default BulkSearchModal;
