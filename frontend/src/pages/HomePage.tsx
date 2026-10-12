import React, { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Search,
  ArrowRight,
  ClipboardList,
  UploadCloud,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  ChevronRight,
  Sparkles,
  FileSpreadsheet,
  CheckCircle2,
  AlertCircle,
  FileUp,
} from "lucide-react";
import productService from "../services/productService";
import uploadService from "../services/uploadService";
import { ProductFamilySummary, PlatformListing } from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";
import BulkSearchModal from "../components/layout/BulkSearchModal";
import SplashScreen from "../components/layout/SplashScreen";

export const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  // Splash screen after login
  const [showSplash, setShowSplash] = useState<boolean>(
    Boolean(location.state?.justLoggedIn)
  );

  // Master Excel status & first-time upload state
  const [hasMasterExcel, setHasMasterExcel] = useState<boolean>(true);
  const [skippedExcel, setSkippedExcel] = useState<boolean>(false);
  const [isUploadingExcel, setIsUploadingExcel] = useState<boolean>(false);
  const [excelUploadProgress, setExcelUploadProgress] = useState<number>(0);
  const [excelError, setExcelError] = useState<string | null>(null);
  const [excelSuccess, setExcelSuccess] = useState<string | null>(null);

  // Search state (starts BLANK as requested)
  const [searchTerm, setSearchTerm] = useState("");
  const [hasSearched, setHasSearched] = useState(false);
  const [results, setResults] = useState<ProductFamilySummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [expandedCardId, setExpandedCardId] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<string>("relevance");

  // Bulk / CSV search modal state
  const [isBulkModalOpen, setIsBulkModalOpen] = useState(false);
  const [bulkModalMode, setBulkModalMode] = useState<"paste" | "csv">("paste");

  // Check Master Excel configuration status on mount
  useEffect(() => {
    uploadService
      .getMasterDataStatus()
      .then((st) => {
        setHasMasterExcel(Boolean(st.is_configured));
      })
      .catch(() => {
        // Fallback default to showing search
        setHasMasterExcel(true);
      });
  }, []);

  const handleSearch = async (queryToSearch?: string) => {
    const q = queryToSearch !== undefined ? queryToSearch : searchTerm;
    if (!q || !q.trim()) return;

    setIsLoading(true);
    setHasSearched(true);
    try {
      const data = await productService.searchProducts(q.trim(), 24);
      setResults(data);
      if (data.length > 0 && !expandedCardId) {
        setExpandedCardId(data[0].family_id);
      }
    } catch {
      // Fallback
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleSearch();
    }
  };

  const handleChipClick = (term: string) => {
    setSearchTerm(term);
    handleSearch(term);
  };

  const toggleExpand = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedCardId(expandedCardId === id ? null : id);
  };

  const handleCardClick = (familyId: string) => {
    navigate(`/products/${encodeURIComponent(familyId)}`);
  };

  const handleBulkSearch = async (identifiers: string[]) => {
    if (identifiers.length === 0) return;
    setIsLoading(true);
    setHasSearched(true);
    try {
      const data = await productService.bulkSearch(identifiers);
      setResults(data);
      if (data.length > 0) {
        setExpandedCardId(data[0].family_id);
      }
    } catch {
      // Handle error
    } finally {
      setIsLoading(false);
    }
  };

  // Master Excel file drop / selection
  const handleExcelFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith(".xlsx") && !file.name.endsWith(".xls")) {
      setExcelError("Please select a valid Excel file (.xlsx or .xls).");
      return;
    }

    setExcelError(null);
    setIsUploadingExcel(true);
    setExcelUploadProgress(15);

    try {
      const res = await uploadService.uploadMasterExcel(file, (pct) => {
        setExcelUploadProgress(Math.max(15, pct));
      });
      setExcelUploadProgress(100);
      setExcelSuccess(res.message || "Master Excel successfully uploaded and validated.");
      setTimeout(() => {
        setHasMasterExcel(true);
      }, 1200);
    } catch (err: any) {
      setExcelError(err.response?.data?.detail || err.message || "Failed to upload Excel catalogue.");
    } finally {
      setIsUploadingExcel(false);
    }
  };

  // Sort results in-place
  const sortedResults = [...results].sort((a, b) => {
    if (sortBy === "price_asc") return a.lowest_price - b.lowest_price;
    if (sortBy === "price_desc") return b.lowest_price - a.lowest_price;
    if (sortBy === "variants") return b.variants_count - a.variants_count;
    if (sortBy === "name") return a.title.localeCompare(b.title);
    return b.platforms_count - a.platforms_count; // relevance
  });

  return (
    <>
      {/* Animated Splash Screen if just logged in */}
      {showSplash && (
        <SplashScreen onComplete={() => setShowSplash(false)} maxWaitSeconds={40} />
      )}

      <div className={`max-w-7xl mx-auto px-4 sm:px-8 ${!hasSearched ? "py-4 sm:py-6" : "py-8 sm:py-12"}`}>
        {/* FIRST-TIME MASTER EXCEL UPLOAD SECTION */}
        {!hasMasterExcel && !skippedExcel ? (
          <div className="min-h-[calc(100vh-180px)] flex flex-col items-center justify-center -mt-6 sm:-mt-8">
            <div className="max-w-2xl w-full bg-white rounded-3xl border border-slate-200/90 shadow-sm p-8 sm:p-10 space-y-6 animate-in fade-in zoom-in-95 duration-300">
              <div className="text-center space-y-2">
                <div className="w-16 h-16 rounded-2xl bg-sky-50 text-sky-600 flex items-center justify-center mx-auto mb-4 border border-sky-100 shadow-2xs">
                  <FileSpreadsheet className="w-8 h-8" />
                </div>
                <h2 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
                  Upload Master Excel Catalogue
                </h2>
                <p className="text-sm text-slate-500 font-medium max-w-md mx-auto">
                  First-time setup: Upload your Columbia Master Excel sheet (.xlsx, .xls) to map SKUs, EANs, and Style Codes across all 7 partner platforms.
                </p>
              </div>

              {/* Error & Success Banners */}
              {excelError && (
                <div className="p-4 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-semibold flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{excelError}</span>
                </div>
              )}
              {excelSuccess && (
                <div className="p-4 rounded-2xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-semibold flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                  <span>{excelSuccess}</span>
                </div>
              )}

              {/* Drag & Drop Area */}
              <div className="relative border-2 border-dashed border-slate-200 hover:border-sky-400 rounded-2xl p-8 sm:p-10 text-center transition-colors bg-slate-50/50 hover:bg-sky-50/20 group">
                <input
                  type="file"
                  accept=".xlsx,.xls"
                  onChange={handleExcelFileUpload}
                  disabled={isUploadingExcel}
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
                />
                <div className="space-y-3">
                  <FileUp className="w-10 h-10 text-slate-400 group-hover:text-sky-500 mx-auto transition-colors" />
                  <div>
                    <span className="text-sm font-bold text-slate-800 group-hover:text-sky-600 transition-colors">
                      Click to select file or drag & drop
                    </span>
                    <p className="text-xs text-slate-400 mt-1">
                      Accepts official Columbia master Excel sheet (.xlsx, .xls)
                    </p>
                  </div>
                </div>
              </div>

              {/* Upload Progress Bar */}
              {isUploadingExcel && (
                <div className="space-y-2">
                  <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-[#079FE0] h-full rounded-full transition-all duration-300"
                      style={{ width: `${excelUploadProgress}%` }}
                    />
                  </div>
                  <p className="text-xs text-center font-medium text-slate-500">
                    Parsing and validating catalogue ({excelUploadProgress}%)...
                  </p>
                </div>
              )}

              {/* Skip Button */}
              <div className="pt-2 text-center">
                <button
                  type="button"
                  onClick={() => setSkippedExcel(true)}
                  className="text-xs font-bold text-slate-500 hover:text-sky-600 transition-colors cursor-pointer"
                >
                  Or skip and browse existing scraped intelligence directly →
                </button>
              </div>
            </div>
          </div>
        ) : (
          /* PRODUCT SEARCH VIEW (REPLACES EXCEL UPLOAD SECTION) */
          <>
            {/* Hero Section */}
            <div
              className={`text-center max-w-3xl mx-auto space-y-4 transition-all duration-300 ${
                !hasSearched
                  ? "min-h-[calc(100vh-180px)] flex flex-col items-center justify-center -mt-6 sm:-mt-8"
                  : "mb-10"
              }`}
            >
              <div className="w-full space-y-4">
                <h1 className="text-4xl sm:text-5xl font-black text-slate-900 tracking-tight">
                  Find your product.
                  <br />
                  <span className="text-[#079FE0]">Compare everything.</span>
                </h1>
                <p className="text-sm sm:text-base text-slate-500 font-medium">
                  Search across 7 platforms to get prices, variants, offers and availability in one place.
                </p>

                {/* Large Search Bar (starts blank as requested) */}
                <div className="pt-3">
                  <div className="relative flex items-center bg-white rounded-full border border-slate-200/90 shadow-lg shadow-slate-200/60 p-2 sm:p-2.5 focus-within:ring-3 focus-within:ring-sky-500/20 focus-within:border-sky-500 transition-all max-w-3xl mx-auto">
                    <Search className="w-6 h-6 text-sky-500 ml-4 shrink-0" />
                    <input
                      type="text"
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder="Search by SKU, EAN, Style or product name..."
                      className="w-full px-4 py-2.5 sm:py-3 text-base sm:text-lg text-slate-900 placeholder:text-slate-400 focus:outline-none bg-transparent font-medium"
                    />
                    <button
                      onClick={() => handleSearch()}
                      disabled={isLoading || !searchTerm.trim()}
                      className="px-8 py-3 bg-[#079FE0] hover:bg-[#068ec8] active:bg-[#057ea0] disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm sm:text-base font-bold rounded-full transition-all flex items-center gap-2 shrink-0 shadow-md cursor-pointer"
                    >
                      <span>Search</span>
                      <ArrowRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Action Pills below Search */}
                <div className="flex items-center justify-center gap-4 text-xs font-medium text-slate-600 pt-2">
                  <button
                    onClick={() => {
                      setBulkModalMode("paste");
                      setIsBulkModalOpen(true);
                    }}
                    className="inline-flex items-center gap-1.5 hover:text-sky-600 transition-colors cursor-pointer"
                  >
                    <ClipboardList className="w-3.5 h-3.5 text-slate-400" />
                    <span>Paste multiple SKUs / EANs</span>
                  </button>
                  <span className="text-slate-300">|</span>
                  <button
                    onClick={() => {
                      setBulkModalMode("csv");
                      setIsBulkModalOpen(true);
                    }}
                    className="inline-flex items-center gap-1.5 hover:text-sky-600 transition-colors cursor-pointer"
                  >
                    <UploadCloud className="w-3.5 h-3.5 text-slate-400" />
                    <span>Upload CSV</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Results Section (only displayed once user searches) */}
            {hasSearched && (
              <div className="space-y-6 animate-in fade-in duration-200">
                {/* Results Controls Bar */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-4 border-t border-slate-200/60">
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold text-slate-900">Search Results</h2>
                    <span className="text-xs text-slate-500 font-semibold bg-slate-100 px-2.5 py-0.5 rounded-full border border-slate-200">
                      ({sortedResults.length} products found)
                    </span>
                  </div>

                  <div className="flex items-center gap-2 self-end sm:self-auto">
                    <span className="text-xs text-slate-500 font-medium">Sort by</span>
                    <div className="relative">
                      <select
                        value={sortBy}
                        onChange={(e) => setSortBy(e.target.value)}
                        className="appearance-none bg-white border border-slate-200 rounded-xl px-3 py-1.5 pr-8 text-xs font-semibold text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 transition-all cursor-pointer"
                      >
                        <option value="relevance">Relevance</option>
                        <option value="name">Product Name</option>
                        <option value="price_asc">Lowest Listed Price</option>
                        <option value="price_desc">Highest Listed Price</option>
                        <option value="variants">Variant Count</option>
                      </select>
                      <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    </div>
                  </div>
                </div>

                {/* Product Results List */}
                {isLoading ? (
                  <div className="py-20 text-center space-y-3">
                    <div className="w-8 h-8 border-3 border-sky-200 border-t-sky-500 rounded-full animate-spin mx-auto" />
                    <p className="text-xs font-medium text-slate-500">Searching across 7 platforms in real-time...</p>
                  </div>
                ) : sortedResults.length === 0 ? (
                  <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center space-y-3 max-w-md mx-auto">
                    <Sparkles className="w-8 h-8 text-sky-500 mx-auto" />
                    <h3 className="font-bold text-slate-800">No products found</h3>
                    <p className="text-xs text-slate-500">
                      Try searching by standard Columbia style (e.g. 2005101, WE8479), or searching for shoes, jackets, or pants.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {sortedResults.map((product) => {
                      const isExpanded = expandedCardId === product.family_id;

                      return (
                        <div
                          key={product.family_id}
                          className={`bg-white rounded-2xl border transition-all duration-200 overflow-hidden shadow-2xs ${
                            isExpanded ? "border-sky-300 shadow-md ring-1 ring-sky-200" : "border-slate-200/90 hover:border-slate-300"
                          }`}
                        >
                          {/* Main Product Family Row */}
                          <div
                            onClick={() => handleCardClick(product.family_id)}
                            className="p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 sm:gap-6 cursor-pointer hover:bg-slate-50/40 transition-colors"
                          >
                            {/* Left: Thumbnail & Identifiers */}
                            <div className="flex items-start sm:items-center gap-4 sm:gap-5 flex-1 min-w-0">
                              <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-xl bg-slate-50 border border-slate-100 shrink-0 overflow-hidden p-1 flex items-center justify-center">
                                <img
                                  src={product.image_url || "/vantis_logo.png"}
                                  alt={product.title}
                                  className="w-full h-full object-contain"
                                  loading="lazy"
                                  onError={(e) => {
                                    (e.target as HTMLImageElement).src = "/vantis_logo.png";
                                  }}
                                />
                              </div>

                              <div className="space-y-1.5 min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="text-[11px] font-bold text-sky-700 bg-sky-50 px-2.5 py-0.5 rounded-full border border-sky-100">
                                    {product.category}
                                  </span>
                                  {product.style && (
                                    <span className="text-[11px] font-mono font-bold text-slate-700 bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                                      Style: {product.style}
                                    </span>
                                  )}
                                  {product.ean && (
                                    <span className="text-[11px] font-mono text-slate-500 bg-slate-50 px-2 py-0.5 rounded border border-slate-200/60 hidden sm:inline-block">
                                      EAN: {product.ean}
                                    </span>
                                  )}
                                </div>

                                <h3 className="text-base sm:text-lg font-bold text-slate-900 group-hover:text-sky-600 transition-colors line-clamp-1">
                                  {product.title}
                                </h3>

                                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 font-medium">
                                  <span>{product.variants_count} Variants</span>
                                  <span>•</span>
                                  <span>{product.sizes_count} Sizes</span>
                                  <span>•</span>
                                  <span className="font-semibold text-slate-700">
                                    Available on {product.platforms_count} of 7 platforms
                                  </span>
                                </div>
                              </div>
                            </div>

                            {/* Right: Lowest Price & Compare CTAs */}
                            <div className="flex items-center justify-between md:justify-end gap-6 pt-3 md:pt-0 border-t md:border-t-0 border-slate-100 shrink-0">
                              <div className="text-left md:text-right">
                                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                                  Lowest Price
                                </span>
                                <div className="flex items-baseline gap-2">
                                  <span className="text-2xl font-black text-slate-900">
                                    ₹{product.lowest_price.toLocaleString("en-IN")}
                                  </span>
                                  {product.mrp && product.mrp > product.lowest_price && (
                                    <span className="text-xs text-slate-400 line-through font-semibold">
                                      ₹{product.mrp.toLocaleString("en-IN")}
                                    </span>
                                  )}
                                </div>
                                {Boolean(product.discount_percent && product.discount_percent > 0) && (
                                  <span className="text-[11px] font-bold text-emerald-600 block">
                                    Up to {product.discount_percent}% off
                                  </span>
                                )}
                              </div>

                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={(e) => toggleExpand(product.family_id, e)}
                                  className="p-2 sm:px-3 sm:py-2 rounded-xl border border-slate-200 hover:border-slate-300 text-slate-700 text-xs font-semibold flex items-center gap-1.5 transition-all bg-white hover:bg-slate-50 cursor-pointer shadow-2xs"
                                >
                                  <span className="hidden sm:inline">
                                    {isExpanded ? "Hide 7 Platforms" : "Quick View"}
                                  </span>
                                  {isExpanded ? (
                                    <ChevronUp className="w-4 h-4" />
                                  ) : (
                                    <ChevronDown className="w-4 h-4" />
                                  )}
                                </button>

                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleCardClick(product.family_id);
                                  }}
                                  className="px-4 py-2 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs font-bold rounded-xl shadow-xs transition-colors flex items-center gap-1 cursor-pointer"
                                >
                                  <span>Details</span>
                                  <ChevronRight className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                          </div>

                          {/* Expandable 7-Platform Breakdown Grid */}
                          {isExpanded && (
                            <div className="bg-[#EAF6FE]/40 border-t border-sky-100 p-4 sm:p-6 space-y-4 animate-in fade-in duration-200">
                              <div className="flex items-center justify-between text-xs font-bold text-slate-700">
                                <span>Platform Price & Stock Comparison</span>
                                <span className="text-sky-700">7 Platforms Tracked</span>
                              </div>

                              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                                {product.platforms.map((listing: PlatformListing) => {
                                  const isLowest =
                                    listing.price !== null &&
                                    listing.price !== undefined &&
                                    listing.price <= product.lowest_price;

                                  return (
                                    <div
                                      key={listing.platform_key}
                                      className={`p-3.5 rounded-xl border transition-all ${
                                        listing.price !== null
                                          ? isLowest
                                            ? "bg-white border-emerald-300 shadow-xs ring-1 ring-emerald-200"
                                            : "bg-white border-slate-200/90 shadow-2xs"
                                          : "bg-slate-50/70 border-slate-200/50 opacity-60"
                                      }`}
                                    >
                                      {/* Platform Header */}
                                      <div className="flex items-center justify-between mb-2">
                                        <div className="flex items-center gap-2">
                                          <PlatformLogo
                                            platform={listing.platform}
                                            className="h-4 w-auto max-w-16"
                                          />
                                          <span className="text-xs font-bold text-slate-800">
                                            {listing.platform_name}
                                          </span>
                                        </div>
                                        {isLowest && listing.price && (
                                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800">
                                            Lowest
                                          </span>
                                        )}
                                      </div>

                                      {/* Price & Stock */}
                                      {listing.price !== null && listing.price !== undefined ? (
                                        <div className="space-y-1">
                                          <div className="flex items-baseline justify-between">
                                            <span className="text-base font-black text-slate-900">
                                              ₹{listing.price.toLocaleString("en-IN")}
                                            </span>
                                            {listing.mrp && listing.mrp > listing.price && (
                                              <span className="text-[11px] text-slate-400 line-through">
                                                ₹{listing.mrp.toLocaleString("en-IN")}
                                              </span>
                                            )}
                                          </div>
                                          <div className="flex items-center justify-between text-[11px]">
                                            <span
                                              className={`font-semibold ${
                                                listing.availability_status === "In stock"
                                                  ? "text-emerald-600"
                                                  : listing.availability_status === "Limited stock"
                                                  ? "text-amber-600"
                                                  : "text-rose-500"
                                              }`}
                                            >
                                              {listing.availability_status}
                                            </span>
                                            <span className="text-slate-400">{listing.sizes_summary}</span>
                                          </div>
                                        </div>
                                      ) : (
                                        <div className="py-2 text-center">
                                          <span className="text-xs font-semibold text-slate-400">
                                            Not listed / Out of stock
                                          </span>
                                        </div>
                                      )}

                                      {/* Outbound Link */}
                                      {listing.url && listing.price !== null && (
                                        <div className="pt-2 mt-2 border-t border-slate-100 flex justify-end">
                                          <a
                                            href={listing.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            onClick={(e) => e.stopPropagation()}
                                            className="inline-flex items-center gap-1 text-[11px] font-semibold text-sky-600 hover:text-sky-700"
                                          >
                                            <span>View Listing</span>
                                            <ExternalLink className="w-3 h-3" />
                                          </a>
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Bulk Search Modal */}
      <BulkSearchModal
        isOpen={isBulkModalOpen}
        onClose={() => setIsBulkModalOpen(false)}
        onSearch={handleBulkSearch}
        mode={bulkModalMode}
      />
    </>
  );
};

export default HomePage;
