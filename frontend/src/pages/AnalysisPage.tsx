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

  // Pop-up modal state
  const [modalProduct, setModalProduct] = useState<AnalyticsProductRow | null>(null);
  const [historyData, setHistoryData] = useState<ProductPriceHistoryResponse | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState<boolean>(false);
  const [selectedRange, setSelectedRange] = useState<string>("ALL");

  useEffect(() => {
    loadProductList(1);
  }, [category, platform, sortBy]);

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

      // User requirement: "in data analysis dont show anything unless there is a price change in any platform"
      const withChanges = (data.products || []).filter(
        (p) => p.price_change_percent !== 0 || p.min_recorded_price !== p.max_recorded_price
      );
      setProducts(withChanges);
      setTotalRecords(data.total_records);
      setTotalPages(data.total_pages);
      setCurrentPage(data.page);
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
              <option value="adv">Advaatars</option>
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
        </div>
      </div>

      {/* Main Product Price Change List (Fixed Container with Internal Component Scrolling) */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden bg-white rounded-2xl border border-slate-200/90 shadow-2xs">
        {/* Table Header (Fixed shrink-0) */}
        <div className="shrink-0 p-3.5 sm:px-6 bg-slate-50/80 border-b border-slate-200/80 flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
          <div className="flex-1">Product &amp; Style Code</div>
          <div className="hidden sm:block w-36 text-center">Historical Trend</div>
          <div className="w-28 text-right">Recorded Range</div>
          <div className="w-28 text-right">Current Price</div>
          <div className="w-32 text-right">Price Status</div>
          <div className="w-24 text-right">Graph</div>
        </div>

        {/* Scrollable Component Body (flex-1 overflow-y-auto) */}
        <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {isLoadingList ? (
            <div className="py-24 text-center space-y-3">
              <div className="w-8 h-8 border-3 border-sky-200 border-t-[#079FE0] rounded-full animate-spin mx-auto" />
              <p className="text-xs font-semibold text-slate-500">Querying Supabase real price telemetry...</p>
            </div>
          ) : products.length === 0 ? (
            <div className="py-20 text-center space-y-3 max-w-sm mx-auto">
              <Sparkles className="w-8 h-8 text-[#079FE0] mx-auto" />
              <h3 className="font-bold text-slate-800 text-sm">No products found</h3>
              <p className="text-xs text-slate-500">Try adjusting your category filter, platform, or search query.</p>
            </div>
          ) : (
            products.map((prod) => {
              const isDrop = prod.price_change_percent < 0;
              const isRise = prod.price_change_percent > 0;

              return (
                <div
                  key={prod.family_id}
                  onClick={() => openGraphModal(prod)}
                  className="p-3.5 sm:px-6 flex items-center justify-between gap-4 hover:bg-sky-50/30 transition-colors cursor-pointer group"
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

                  {/* Sparkline Column */}
                  <div className="hidden sm:flex items-center justify-center w-36 shrink-0">
                    {prod.sparkline && prod.sparkline.length > 1 ? (
                      <div className="w-28 h-7 flex items-end gap-1 px-1">
                        {prod.sparkline.map((val, idx) => {
                          const minV = Math.min(...prod.sparkline);
                          const maxV = Math.max(...prod.sparkline);
                          const heightPct = maxV === minV ? 50 : Math.max(15, Math.round(((val - minV) / (maxV - minV)) * 85));
                          return (
                            <div
                              key={idx}
                              style={{ height: `${heightPct}%` }}
                              className={`flex-1 rounded-t-xs transition-all ${
                                isDrop ? "bg-emerald-400" : isRise ? "bg-rose-400" : "bg-sky-400"
                              }`}
                              title={`₹${val}`}
                            />
                          );
                        })}
                      </div>
                    ) : (
                      <span className="text-slate-300 text-xs">—</span>
                    )}
                  </div>

                  {/* Recorded Range */}
                  <div className="w-28 text-right shrink-0">
                    <span className="text-xs font-bold text-slate-600 block">
                      {formatCurrency(prod.min_recorded_price)}
                    </span>
                    <span className="text-[10px] text-slate-400 font-medium block">
                      to {formatCurrency(prod.max_recorded_price)}
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

                  {/* Action CTA */}
                  <div className="w-24 text-right shrink-0">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        openGraphModal(prod);
                      }}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-[#079FE0] text-slate-700 hover:text-white text-xs font-bold transition-all cursor-pointer shadow-2xs"
                    >
                      <LineChartIcon className="w-3.5 h-3.5" />
                      <span>Graph</span>
                    </button>
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
                ) : historyData && historyData.history_points && historyData.history_points.length > 0 ? (
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
                  <div className="h-64 flex flex-col items-center justify-center text-slate-400 space-y-2">
                    <LineChartIcon className="w-8 h-8 stroke-1 text-slate-300" />
                    <p className="text-xs font-semibold">No price history points recorded yet for this product.</p>
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
