import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import {
  Search,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Sparkles,
  ExternalLink,
  X,
  LineChart as LineChartIcon,
  Database,
  ArrowRight,
  Maximize2,
  Minimize2,
} from "lucide-react";
import analyticsService from "../services/analyticsService";
import {
  AnalyticsProductRow,
  ProductPriceHistoryResponse,
} from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";

export const AnalysisPage: React.FC = () => {
  const navigate = useNavigate();

  // Filter & list state
  const [products, setProducts] = useState<AnalyticsProductRow[]>([]);
  const [totalRecords, setTotalRecords] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [pageSize] = useState<number>(20);
  const [isLoadingList, setIsLoadingList] = useState<boolean>(true);

  const [searchTerm, setSearchTerm] = useState<string>("");
  const [category, setCategory] = useState<string>("All");
  const [platform, setPlatform] = useState<string>("All");
  const [sortBy, setSortBy] = useState<string>("price_change");

  // Fullscreen table toggle
  const [isFullscreenTable, setIsFullscreenTable] = useState<boolean>(false);

  // Active on-screen graph product & history
  const [activeInlineProduct, setActiveInlineProduct] = useState<AnalyticsProductRow | null>(null);
  const [inlineHistoryData, setInlineHistoryData] = useState<ProductPriceHistoryResponse | null>(null);
  const [isLoadingInlineHistory, setIsLoadingInlineHistory] = useState<boolean>(false);

  // Pop-up modal state
  const [modalProduct, setModalProduct] = useState<AnalyticsProductRow | null>(null);
  const [historyData, setHistoryData] = useState<ProductPriceHistoryResponse | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState<boolean>(false);
  const [selectedRange, setSelectedRange] = useState<string>("ALL");

  const flattenedHistoryRows = React.useMemo(() => {
    if (!historyData || !historyData.history_points) return [];
    const rows: Array<{
      date: string;
      platform: string;
      platformName: string;
      price: number;
      currentPrice: number;
      diff: number;
      diffPct: number;
    }> = [];

    const statsMap: Record<string, any> = {};
    (historyData.platform_stats || []).forEach((ps) => {
      statsMap[ps.platform] = ps;
    });

    historyData.history_points.forEach((pt) => {
      const d = pt.date;
      Object.keys(pt).forEach((k) => {
        if (k !== "date" && pt[k] !== null && pt[k] !== undefined) {
          const price = Number(pt[k]);
          const ps = statsMap[k];
          const curr = ps?.current_price || price;
          const diff = curr - price;
          const diffPct = price > 0 ? Math.round(((curr - price) / price) * 100) : 0;
          rows.push({
            date: d,
            platform: k,
            platformName: ps?.platform_name || k.toUpperCase(),
            price,
            currentPrice: curr,
            diff,
            diffPct,
          });
        }
      });
    });

    return rows.reverse();
  }, [historyData]);

  useEffect(() => {
    loadProductList(1);
  }, [category, platform, sortBy]);

  const selectInlineProduct = async (prod: AnalyticsProductRow, range: string = selectedRange) => {
    setActiveInlineProduct(prod);
    setIsLoadingInlineHistory(true);
    try {
      const hist = await analyticsService.getPriceHistory(prod.family_id, range);
      setInlineHistoryData(hist);
    } catch {
      // Keep existing
    } finally {
      setIsLoadingInlineHistory(false);
    }
  };

  const loadProductList = async (pageToLoad: number = 1) => {
    setIsLoadingList(true);
    try {
      const data = await analyticsService.getProducts({
        search: searchTerm.trim() || undefined,
        category: category !== "All" ? category : undefined,
        platform: platform !== "All" ? platform : undefined,
        sort_by: sortBy,
        page: pageToLoad,
        page_size: pageSize,
      });

      const items = data.products || [];
      setProducts(items);
      setTotalRecords(data.total_records);
      setTotalPages(data.total_pages);
      setCurrentPage(data.page);

      if (items.length > 0) {
        selectInlineProduct(items[0], selectedRange);
      }
    } catch {
      // Keep existing list on failure
    } finally {
      setIsLoadingList(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadProductList(1);
  };

  // Open Pop-up Graph Modal
  const openGraphModal = async (prod: AnalyticsProductRow) => {
    setModalProduct(prod);
    setIsLoadingHistory(true);
    try {
      const hist = await analyticsService.getPriceHistory(prod.family_id, selectedRange);
      setHistoryData(hist);
    } catch {
      // Fallback
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const closeGraphModal = () => {
    setModalProduct(null);
    setHistoryData(null);
  };

  const handleRangeChange = async (r: string) => {
    setSelectedRange(r);
    if (activeInlineProduct) {
      selectInlineProduct(activeInlineProduct, r);
    }
    if (modalProduct) {
      setIsLoadingHistory(true);
      try {
        const hist = await analyticsService.getPriceHistory(modalProduct.family_id, r);
        setHistoryData(hist);
      } catch {
        // Fallback
      } finally {
        setIsLoadingHistory(false);
      }
    }
  };

  // Color mapping for 7 platforms
  const platformColors: Record<string, string> = {
    amazon: "#0b192c",
    columbia: "#079FE0",
    tata: "#b81f33",
    tata_lux: "#8b5a2b",
    myntra: "#e11d48",
    adv: "#059669",
    ajio: "#475569",
  };

  const formatCurrency = (val: number | null | undefined) => {
    if (val === null || val === undefined) return "—";
    return `₹${val.toLocaleString("en-IN")}`;
  };

  return (
    <div className="h-full flex flex-col overflow-hidden max-w-7xl w-full mx-auto px-4 sm:px-8 py-3 space-y-3">
      {/* Page Title & Count (Structured identically to View Data) */}
      <div className="shrink-0 space-y-1">
        <div className="flex items-center gap-3">
          <h1 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight">
            Product Price Analysis &amp; Movements
          </h1>
          <span className="bg-[#EAF6FE] text-[#079FE0] font-extrabold text-xs sm:text-sm px-3 py-1 rounded-full border border-sky-200">
            {totalRecords.toLocaleString("en-IN")} products
          </span>
        </div>
        <p className="text-xs sm:text-sm text-slate-500 font-medium">
          Products with verified price changes across platforms. Click any product row to open the interactive price history graph.
        </p>
      </div>

      {/* Filter and Control Bar (Fixed shrink-0) */}
      <div className="shrink-0 bg-white rounded-2xl border border-slate-200/90 shadow-2xs p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        {/* Search */}
        <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by product, style code or category..."
            className="w-full pl-9 pr-16 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0] text-slate-900 placeholder:text-slate-400 font-semibold"
          />
          <button
            type="submit"
            className="absolute right-1 top-1/2 -translate-y-1/2 px-2.5 py-1 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs font-bold rounded-lg transition-colors cursor-pointer"
          >
            Filter
          </button>
        </form>

        {/* Dropdowns */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Category */}
          <div className="relative">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 pr-7 text-xs font-bold text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 cursor-pointer"
            >
              <option value="All">All Categories</option>
              <option value="Jackets">Jackets</option>
              <option value="Shoes & Boots">Shoes & Boots</option>
              <option value="Fleece">Fleece</option>
              <option value="Pants & Shorts">Pants & Shorts</option>
              <option value="Shirts">Shirts</option>
              <option value="Backpacks & Bags">Backpacks & Bags</option>
              <option value="Accessories">Accessories</option>
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* Platform */}
          <div className="relative">
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 pr-7 text-xs font-bold text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 cursor-pointer"
            >
              <option value="All">All Platforms (7)</option>
              <option value="amazon">Amazon</option>
              <option value="columbia">Columbia India</option>
              <option value="tata">Tata CLiQ</option>
              <option value="tata_lux">Tata CLiQ Luxury</option>
              <option value="myntra">Myntra</option>
              <option value="adv">Adventuras</option>
              <option value="ajio">AJIO</option>
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* Sort */}
          <div className="relative">
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 pr-7 text-xs font-bold text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 cursor-pointer"
            >
              <option value="price_change">Price Movements</option>
              <option value="price_drop">Biggest Price Drops</option>
              <option value="price_asc">Lowest Current Price</option>
              <option value="price_desc">Highest Current Price</option>
              <option value="name">Product Name</option>
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* Fullscreen Table Mode Button */}
          <button
            type="button"
            onClick={() => setIsFullscreenTable(!isFullscreenTable)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer border ${
              isFullscreenTable
                ? "bg-slate-900 text-white border-slate-900 shadow-xs"
                : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
            }`}
            title={isFullscreenTable ? "Exit Fullscreen" : "Fullscreen Table Mode"}
          >
            {isFullscreenTable ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            <span>{isFullscreenTable ? "Exit Fullscreen" : "Fullscreen Table"}</span>
          </button>
        </div>
      </div>

      {/* Main Product Price Change List (Supports Fullscreen Table) */}
      <div
        className={
          isFullscreenTable
            ? "fixed inset-0 z-50 bg-white p-4 sm:p-6 flex flex-col space-y-3 overflow-hidden animate-in fade-in"
            : "flex-1 min-h-0 max-h-[580px] flex flex-col overflow-hidden bg-white rounded-2xl border border-slate-200/90 shadow-2xs"
        }
      >
        {isFullscreenTable && (
          <div className="shrink-0 flex items-center justify-between pb-3 border-b border-slate-200">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-black text-slate-900">
                Fullscreen Price Intelligence Table
              </h2>
              <span className="bg-[#EAF6FE] text-[#079FE0] font-extrabold text-xs px-2.5 py-0.5 rounded-full border border-sky-200">
                {totalRecords} products
              </span>
            </div>
            <button
              onClick={() => setIsFullscreenTable(false)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900 text-white text-xs font-bold hover:bg-slate-800 transition-all cursor-pointer shadow-xs"
            >
              <Minimize2 className="w-3.5 h-3.5" />
              <span>Exit Fullscreen</span>
            </button>
          </div>
        )}

        {/* Table Header (Fixed shrink-0) */}
        <div className="shrink-0 p-3.5 sm:px-6 bg-slate-50/80 border-b border-slate-200/80 flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
          <div className="flex-1">Product &amp; Style Code</div>
          <div className="w-28 text-right">Previous Price</div>
          <div className="w-28 text-right">Current Price</div>
          <div className="w-32 text-right">Price Status</div>
        </div>

        {/* Scrollable Component Body (flex-1 overflow-y-auto) */}
        <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {isLoadingList ? (
            <div className="py-24 text-center space-y-3">
              <div className="w-8 h-8 border-3 border-sky-200 border-t-[#079FE0] rounded-full animate-spin mx-auto" />
              <p className="text-xs font-semibold text-slate-500">Querying Supabase real price telemetry...</p>
            </div>
          ) : products.length === 0 ? (
            <div className="py-20 text-center space-y-3 max-w-md mx-auto px-4">
              <Sparkles className="w-8 h-8 text-[#079FE0] mx-auto" />
              <h3 className="font-bold text-slate-800 text-sm">No Price Changes Recorded Yet</h3>
              <p className="text-xs text-slate-500 leading-relaxed">
                The Data Analysis view exclusively tracks products with verified changes in current selling price (not MRP) on a platform over time (e.g. ₹2,000 moving to ₹2,200). Products will appear here once consecutive scrape runs confirm a price shift.
              </p>
            </div>
          ) : (
            products.map((prod) => {
              const isDrop = prod.price_change_percent < 0;
              const isRise = prod.price_change_percent > 0;
              const isSelectedRow = activeInlineProduct?.family_id === prod.family_id;

              return (
                <div
                  key={prod.family_id}
                  onClick={() => openGraphModal(prod)}
                  className={`p-3.5 sm:px-6 flex items-center justify-between gap-4 transition-colors cursor-pointer group hover:bg-sky-50/50 ${
                    isSelectedRow ? "bg-sky-50/60 border-l-4 border-l-[#079FE0]" : ""
                  }`}
                >
                  {/* Left: Product Thumbnail & Identifiers */}
                  <div className="flex items-center gap-3.5 flex-1 min-w-0">
                    <div className="w-12 h-12 rounded-xl bg-slate-50 border border-slate-100 shrink-0 overflow-hidden p-1 flex items-center justify-center">
                      <img
                        src={prod.image_url || "/vantis_logo.png"}
                        alt={prod.title}
                        className="w-full h-full object-contain"
                        loading="lazy"
                        onError={(e) => {
                          (e.target as HTMLImageElement).src = "/vantis_logo.png";
                        }}
                      />
                    </div>
                    <div className="min-w-0 space-y-0.5">
                      <h3 className="text-xs sm:text-sm font-bold text-slate-900 group-hover:text-[#079FE0] transition-colors line-clamp-1">
                        {prod.title}
                      </h3>
                      <div className="flex flex-wrap items-center gap-1.5 text-xs">
                        {prod.style && (
                          <span className="font-mono font-bold text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded text-[10px]">
                            {prod.style}
                          </span>
                        )}
                        <span className="text-slate-400 font-medium text-[10px]">
                          {prod.category} • {prod.gender}
                        </span>
                        <span className="text-[#079FE0] font-bold text-[10px] bg-sky-50 px-1.5 py-0.5 rounded">
                          {prod.platforms_count} platforms
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Previous Price */}
                  <div className="w-28 text-right shrink-0">
                    <span className="text-xs font-bold text-slate-700 block">
                      {prod.previous_price && prod.previous_price !== prod.lowest_price
                        ? formatCurrency(prod.previous_price)
                        : "—"}
                    </span>
                    <span className="text-[10px] text-slate-400 font-medium block">
                      {prod.change_platform ? `${prod.change_platform.toUpperCase()} Before` : "Previous"}
                    </span>
                  </div>

                  {/* Current Price */}
                  <div className="w-28 text-right shrink-0">
                    <span className="text-sm font-black text-slate-900 block">
                      {formatCurrency(prod.lowest_price)}
                    </span>
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                      Current Price
                    </span>
                  </div>

                  {/* Price Status % Badge */}
                  <div className="w-32 text-right shrink-0 flex justify-end">
                    {isDrop ? (
                      <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                        <TrendingDown className="w-3.5 h-3.5 shrink-0" />
                        <span>{Math.abs(prod.price_change_percent)}% Drop</span>
                      </div>
                    ) : isRise ? (
                      <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-50 text-rose-700 border border-rose-200">
                        <TrendingUp className="w-3.5 h-3.5 shrink-0" />
                        <span>+{prod.price_change_percent}% Rise</span>
                      </div>
                    ) : (
                      <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 border border-slate-200">
                        <span>Stable</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Pagination Bar (Fixed shrink-0) */}
        {totalPages > 1 && (
          <div className="shrink-0 p-3 sm:px-6 bg-slate-50/80 border-t border-slate-200/80 flex items-center justify-between text-xs text-slate-600 font-semibold">
            <span>
              Showing Page {currentPage} of {totalPages} ({totalRecords} products)
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={currentPage <= 1 || isLoadingList}
                onClick={() => loadProductList(currentPage - 1)}
                className="p-1 rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                disabled={currentPage >= totalPages || isLoadingList}
                onClick={() => loadProductList(currentPage + 1)}
                className="p-1 rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* POP-UP GRAPH MODAL */}
      {modalProduct && (
        <div
          onClick={closeGraphModal}
          className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 sm:p-6 overflow-y-auto animate-in fade-in duration-200"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="bg-white rounded-3xl border border-slate-200 shadow-2xl max-w-4xl w-full max-h-[92vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200"
          >
            {/* Modal Header */}
            <div className="p-6 border-b border-slate-200 flex items-start justify-between gap-4 bg-slate-50/50">
              <div className="flex items-start gap-4 min-w-0">
                <div className="w-16 h-16 rounded-2xl bg-white border border-slate-200/80 shrink-0 overflow-hidden p-1 flex items-center justify-center shadow-xs">
                  <img
                    src={modalProduct.image_url || "/vantis_logo.png"}
                    alt={modalProduct.title}
                    className="w-full h-full object-contain"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = "/vantis_logo.png";
                    }}
                  />
                </div>
                <div className="space-y-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold text-sky-700 bg-sky-100/70 px-2 py-0.5 rounded-full">
                      {modalProduct.category}
                    </span>
                    {modalProduct.style && (
                      <span className="font-mono text-xs font-bold text-slate-700 bg-slate-200/70 px-2 py-0.5 rounded-full">
                        Style: {modalProduct.style}
                      </span>
                    )}
                  </div>
                  <h2 className="text-base sm:text-lg font-black text-slate-900 truncate">
                    {modalProduct.title}
                  </h2>
                  <p className="text-xs text-slate-500 font-medium">
                    Current Best Price:{" "}
                    <span className="font-bold text-slate-900">
                      {formatCurrency(modalProduct.lowest_price)}
                    </span>{" "}
                    • Recorded Range: {formatCurrency(modalProduct.min_recorded_price)} – {formatCurrency(modalProduct.max_recorded_price)}
                  </p>
                </div>
              </div>

              {/* Close Button */}
              <button
                onClick={closeGraphModal}
                className="w-8 h-8 rounded-full border border-slate-200 bg-white hover:bg-slate-100 text-slate-500 hover:text-slate-800 flex items-center justify-center transition-colors cursor-pointer shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 space-y-6 overflow-y-auto flex-1">
              {/* Range Filters */}
              <div className="flex items-center justify-between gap-4">
                <div className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Timeline History
                </div>
                <div className="flex items-center bg-slate-100 p-1 rounded-xl gap-1">
                  {["1W", "1M", "3M", "6M", "ALL"].map((r) => (
                    <button
                      key={r}
                      onClick={() => handleRangeChange(r)}
                      className={`px-3 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                        selectedRange === r
                          ? "bg-white text-slate-900 shadow-xs"
                          : "text-slate-500 hover:text-slate-800"
                      }`}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>

              {/* Interactive Line Chart */}
              <div className="bg-slate-50/50 p-4 rounded-2xl border border-slate-200/80">
                {isLoadingHistory ? (
                  <div className="h-64 flex items-center justify-center">
                    <div className="w-6 h-6 border-2 border-sky-200 border-t-sky-500 rounded-full animate-spin" />
                  </div>
                ) : historyData && historyData.history_points && historyData.history_points.length > 1 ? (
                  <div className="h-64 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={historyData.history_points}
                        margin={{ top: 10, right: 20, left: 0, bottom: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                        <XAxis
                          dataKey="date"
                          stroke="#94a3b8"
                          fontSize={11}
                          tickLine={false}
                          axisLine={{ stroke: "#cbd5e1" }}
                        />
                        <YAxis
                          stroke="#94a3b8"
                          fontSize={11}
                          tickLine={false}
                          axisLine={false}
                          tickFormatter={(val) => `₹${val.toLocaleString("en-IN")}`}
                          domain={["auto", "auto"]}
                        />
                        <Tooltip
                          content={({ active, payload, label }) => {
                            if (!active || !payload || !payload.length) return null;
                            return (
                              <div className="bg-white p-3 rounded-xl border border-slate-200 shadow-xl text-xs space-y-1.5">
                                <div className="font-bold text-slate-800 border-b border-slate-100 pb-1">
                                  {label}
                                </div>
                                {payload.map((item: any, idx: number) => (
                                  <div key={idx} className="flex items-center justify-between gap-4">
                                    <span className="font-medium text-slate-600 capitalize">
                                      {item.name}:
                                    </span>
                                    <span className="font-black text-slate-900">
                                      ₹{Number(item.value).toLocaleString("en-IN")}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            );
                          }}
                        />
                        <Legend
                          wrapperStyle={{ paddingTop: "12px", fontSize: "11px", fontWeight: "600" }}
                        />
                        {/* Lines per platform */}
                        {historyData.platform_stats.map((ps) => (
                          <Line
                            key={ps.platform}
                            type="monotone"
                            dataKey={ps.platform}
                            name={ps.platform_name}
                            stroke={platformColors[ps.platform] || "#64748b"}
                            strokeWidth={2.5}
                            dot={{ r: 4, strokeWidth: 2, fill: "#fff" }}
                            activeDot={{ r: 6 }}
                            connectNulls
                          />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="h-44 flex flex-col items-center justify-center text-slate-500 space-y-2 p-6 bg-white rounded-xl border border-slate-200">
                    <LineChartIcon className="w-7 h-7 stroke-1 text-slate-400" />
                    <p className="text-xs font-bold text-slate-800">Single Scrape Recorded (13 Oct 2026)</p>
                    <p className="text-[11px] text-slate-500 text-center max-w-sm">
                      This product has been recorded once. Multi-point historical price curves will plot across timeline checkpoints automatically as subsequent scraper runs complete.
                    </p>
                  </div>
                )}
              </div>

              {/* Platform Breakdown Cards */}
              <div className="space-y-3">
                <div className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Platform Real-time Price Comparison
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                  {historyData?.platform_stats && historyData.platform_stats.length > 0 ? (
                    historyData.platform_stats.map((stat) => (
                      <div
                        key={stat.platform}
                        className="p-3.5 rounded-2xl border border-slate-200 bg-white shadow-2xs space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <PlatformLogo platform={stat.platform} size="sm" />
                            <span className="text-xs font-bold text-slate-800">{stat.platform_name}</span>
                          </div>
                          <span className="text-xs font-black text-slate-900">
                            {formatCurrency(stat.current_price)}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-[11px] text-slate-500 pt-1 border-t border-slate-100">
                          <span>Low: {formatCurrency(stat.lowest_price)}</span>
                          <span>High: {formatCurrency(stat.highest_price)}</span>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="col-span-full py-4 text-center text-xs text-slate-400 font-medium">
                      Platform statistics will display after history loading finishes.
                    </div>
                  )}
                </div>
              </div>

              {/* Tabular Detail of All Historical Recorded Prices */}
              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                    Tabular Detail of All Historical Prices
                  </h4>
                  <span className="text-[11px] font-semibold text-slate-400">
                    {flattenedHistoryRows.length} historical records
                  </span>
                </div>

                <div className="bg-white rounded-2xl border border-slate-200/90 shadow-2xs overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                          <th className="py-2.5 px-4">Date / Milestone</th>
                          <th className="py-2.5 px-4">Platform</th>
                          <th className="py-2.5 px-4">Recorded Price</th>
                          <th className="py-2.5 px-4">Current Price</th>
                          <th className="py-2.5 px-4 text-right">Price Movement</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 font-medium text-slate-700">
                        {flattenedHistoryRows.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="py-8 text-center text-slate-400">
                              No prior historical checkpoints recorded for this product yet.
                            </td>
                          </tr>
                        ) : (
                          flattenedHistoryRows.map((row, idx) => (
                            <tr key={idx} className="hover:bg-slate-50/60 transition-colors">
                              <td className="py-3 px-4 font-mono font-bold text-slate-800 text-[11px]">
                                {row.date}
                              </td>
                              <td className="py-3 px-4">
                                <div className="flex items-center gap-2">
                                  <PlatformLogo platform={row.platform} size="xs" />
                                  <span className="font-bold text-slate-800">{row.platformName}</span>
                                </div>
                              </td>
                              <td className="py-3 px-4 font-mono font-bold text-slate-900 text-xs">
                                {formatCurrency(row.price)}
                              </td>
                              <td className="py-3 px-4 font-mono text-slate-500">
                                {formatCurrency(row.currentPrice)}
                              </td>
                              <td className="py-3 px-4 text-right">
                                {row.diff < 0 ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                                    {formatCurrency(row.diff)} ({Math.abs(row.diffPct)}% Drop)
                                  </span>
                                ) : row.diff > 0 ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-50 text-rose-700 border border-rose-200">
                                    +{formatCurrency(row.diff)} (+{row.diffPct}% Rise)
                                  </span>
                                ) : (
                                  <span className="text-slate-400 text-[11px]">Stable</span>
                                )}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-4 sm:px-6 bg-slate-50 border-t border-slate-200 flex items-center justify-between">
              <button
                onClick={closeGraphModal}
                className="px-4 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-100 text-xs font-bold text-slate-700 transition-colors cursor-pointer"
              >
                Close
              </button>
              <button
                onClick={() => {
                  closeGraphModal();
                  navigate(`/products/${encodeURIComponent(modalProduct.family_id)}`);
                }}
                className="px-4 py-2 rounded-xl bg-[#079FE0] hover:bg-[#068ec8] text-xs font-bold text-white transition-colors cursor-pointer flex items-center gap-1.5 shadow-xs"
              >
                <span>View Full Product Specifications</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AnalysisPage;
