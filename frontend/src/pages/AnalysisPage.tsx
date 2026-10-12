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
  Layers,
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

      setProducts(data.products);
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
    <div className="max-w-7xl mx-auto px-4 sm:px-8 py-6 sm:py-8 space-y-6">
      {/* Top Header & Supabase Intelligence Banner */}
      <div className="bg-gradient-to-r from-sky-500/10 via-sky-500/5 to-white border border-sky-100 rounded-3xl p-6 sm:p-8 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="space-y-1.5 max-w-2xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sky-100/80 border border-sky-200 text-sky-800 text-xs font-bold tracking-wide">
            <Database className="w-3.5 h-3.5" />
            <span>Supabase Real Price History & Scrape Telemetry</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
            Product Price Analysis & Movements
          </h1>
          <p className="text-sm text-slate-500">
            Real historical multi-platform price changes tracked across 14,696 scrape records. Click any product to launch the interactive multi-platform timeline graph.
          </p>
        </div>

        {/* Intelligence Metric Badges */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 shrink-0">
          <div className="bg-white rounded-2xl border border-slate-200/90 p-3.5 shadow-2xs">
            <span className="text-[11px] font-semibold text-slate-400 block uppercase tracking-wider">Tracked Records</span>
            <span className="text-xl font-black text-slate-900">14,696</span>
          </div>
          <div className="bg-white rounded-2xl border border-slate-200/90 p-3.5 shadow-2xs">
            <span className="text-[11px] font-semibold text-slate-400 block uppercase tracking-wider">Price Movements</span>
            <span className="text-xl font-black text-emerald-600">719+</span>
          </div>
          <div className="bg-white rounded-2xl border border-slate-200/90 p-3.5 shadow-2xs col-span-2 sm:col-span-1">
            <span className="text-[11px] font-semibold text-slate-400 block uppercase tracking-wider">Date Span</span>
            <span className="text-xs font-bold text-slate-700 block mt-1">05 Oct – 12 Oct 2026</span>
          </div>
        </div>
      </div>

      {/* Filter and Control Bar */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-2xs p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Search */}
        <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by product, style code or category..."
            className="w-full pl-10 pr-20 py-2 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 text-slate-900 placeholder:text-slate-400 font-medium"
          />
          <button
            type="submit"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 px-3 py-1 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs font-semibold rounded-lg transition-colors cursor-pointer"
          >
            Filter
          </button>
        </form>

        {/* Dropdowns */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Category */}
          <div className="relative">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 pr-8 text-xs font-semibold text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
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
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* Platform */}
          <div className="relative">
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 pr-8 text-xs font-semibold text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
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
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* Sort */}
          <div className="relative">
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 pr-8 text-xs font-semibold text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
            >
              <option value="price_change">Largest Price Changes (High to Low)</option>
              <option value="price_drop">Biggest Price Drops</option>
              <option value="price_asc">Lowest Current Price</option>
              <option value="price_desc">Highest Current Price</option>
              <option value="name">Product Name</option>
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>
        </div>
      </div>

      {/* Main Product Price Change List */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-2xs overflow-hidden">
        {/* Table Header */}
        <div className="p-4 sm:px-6 bg-slate-50/70 border-b border-slate-200/80 flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
          <div className="flex-1">Product Details & Identifiers</div>
          <div className="hidden sm:block w-36 text-center">Historical Trend</div>
          <div className="w-28 text-right">Recorded Range</div>
          <div className="w-28 text-right">Current Price</div>
          <div className="w-32 text-right">Price Change</div>
          <div className="w-24 text-right">Action</div>
        </div>

        {/* Loading State */}
        {isLoadingList ? (
          <div className="py-24 text-center space-y-3">
            <div className="w-8 h-8 border-3 border-sky-200 border-t-sky-500 rounded-full animate-spin mx-auto" />
            <p className="text-xs font-medium text-slate-500">Querying Supabase historical price telemetry...</p>
          </div>
        ) : products.length === 0 ? (
          <div className="py-20 text-center space-y-3 max-w-sm mx-auto">
            <Sparkles className="w-8 h-8 text-sky-500 mx-auto" />
            <h3 className="font-bold text-slate-800 text-sm">No price change records found</h3>
            <p className="text-xs text-slate-500">Try adjusting your category filter, platform, or search term.</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {products.map((prod) => {
              const isDrop = prod.price_change_percent < 0;
              const isRise = prod.price_change_percent > 0;
              const hasChange = prod.price_change_percent !== 0;

              return (
                <div
                  key={prod.family_id}
                  onClick={() => openGraphModal(prod)}
                  className="p-4 sm:px-6 flex items-center justify-between gap-4 hover:bg-sky-50/30 transition-colors cursor-pointer group"
                >
                  {/* Left: Product Thumbnail & Identifiers */}
                  <div className="flex items-center gap-4 flex-1 min-w-0">
                    <div className="w-14 h-14 rounded-xl bg-slate-50 border border-slate-100 shrink-0 overflow-hidden p-1 flex items-center justify-center">
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
                    <div className="min-w-0 space-y-1">
                      <h3 className="text-sm font-bold text-slate-900 group-hover:text-sky-600 transition-colors line-clamp-1">
                        {prod.title}
                      </h3>
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        {prod.style && (
                          <span className="font-mono font-semibold text-slate-600 bg-slate-100 px-2 py-0.5 rounded text-[11px]">
                            {prod.style}
                          </span>
                        )}
                        <span className="text-slate-400 font-medium text-[11px]">
                          {prod.category} • {prod.gender}
                        </span>
                        <span className="text-sky-600 font-semibold text-[11px] bg-sky-50 px-2 py-0.5 rounded">
                          {prod.platforms_count} platforms
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Sparkline Column */}
                  <div className="hidden sm:flex items-center justify-center w-36 shrink-0">
                    {prod.sparkline && prod.sparkline.length > 1 ? (
                      <div className="w-28 h-8 flex items-end gap-1 px-1">
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
                    <span className="text-xs font-semibold text-slate-500 block">
                      {formatCurrency(prod.min_recorded_price)}
                    </span>
                    <span className="text-[11px] text-slate-400 block">
                      to {formatCurrency(prod.max_recorded_price)}
                    </span>
                  </div>

                  {/* Current Price */}
                  <div className="w-28 text-right shrink-0">
                    <span className="text-sm font-black text-slate-900 block">
                      {formatCurrency(prod.lowest_price)}
                    </span>
                    <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                      Best Price
                    </span>
                  </div>

                  {/* Price Change % Badge */}
                  <div className="w-32 text-right shrink-0 flex justify-end">
                    {isDrop ? (
                      <div className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                        <TrendingDown className="w-3.5 h-3.5 shrink-0" />
                        <span>{Math.abs(prod.price_change_percent)}% Drop</span>
                      </div>
                    ) : isRise ? (
                      <div className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-rose-50 text-rose-700 border border-rose-200">
                        <TrendingUp className="w-3.5 h-3.5 shrink-0" />
                        <span>+{prod.price_change_percent}% Rise</span>
                      </div>
                    ) : (
                      <div className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 border border-slate-200">
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
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-[#079FE0] text-slate-700 hover:text-white text-xs font-semibold transition-all cursor-pointer shadow-2xs"
                    >
                      <LineChartIcon className="w-3.5 h-3.5" />
                      <span>Graph</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Pagination Bar */}
        {totalPages > 1 && (
          <div className="p-4 sm:px-6 bg-slate-50/70 border-t border-slate-200/80 flex items-center justify-between text-xs text-slate-600 font-semibold">
            <span>
              Showing Page {currentPage} of {totalPages} ({totalRecords} products)
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={currentPage <= 1 || isLoadingList}
                onClick={() => loadProductList(currentPage - 1)}
                className="p-1.5 rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                disabled={currentPage >= totalPages || isLoadingList}
                onClick={() => loadProductList(currentPage + 1)}
                className="p-1.5 rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
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
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-100 text-sky-800">
                      {modalProduct.category}
                    </span>
                    {modalProduct.style && (
                      <span className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-slate-200 text-slate-800">
                        Style: {modalProduct.style}
                      </span>
                    )}
                    {modalProduct.ean && (
                      <span className="px-2 py-0.5 rounded text-xs font-mono text-slate-500 bg-slate-100">
                        EAN: {modalProduct.ean}
                      </span>
                    )}
                  </div>
                  <h2 className="text-lg sm:text-xl font-black text-slate-900 tracking-tight line-clamp-2">
                    {modalProduct.title}
                  </h2>
                </div>
              </div>

              {/* Close Button */}
              <button
                onClick={closeGraphModal}
                className="p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-full transition-colors cursor-pointer shrink-0"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Scrollable Body */}
            <div className="p-6 overflow-y-auto space-y-6 flex-1">
              {isLoadingHistory ? (
                <div className="py-24 text-center space-y-3">
                  <div className="w-8 h-8 border-3 border-sky-200 border-t-sky-500 rounded-full animate-spin mx-auto" />
                  <p className="text-xs font-medium text-slate-500">
                    Loading multi-platform historical timeline points...
                  </p>
                </div>
              ) : historyData ? (
                <>
                  {/* KPI Metrics Row */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="bg-slate-50 border border-slate-200/80 rounded-2xl p-4">
                      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                        Current Lowest Price
                      </span>
                      <span className="text-2xl font-black text-slate-900 block mt-1">
                        {formatCurrency(historyData.current_price)}
                      </span>
                    </div>

                    <div className="bg-slate-50 border border-slate-200/80 rounded-2xl p-4">
                      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                        Recorded Price Range
                      </span>
                      <span className="text-2xl font-black text-slate-900 block mt-1">
                        {formatCurrency(historyData.price_range)}
                      </span>
                      <span className="text-xs font-bold text-slate-500 block">
                        Spread: {historyData.price_range_percent}%
                      </span>
                    </div>

                    <div className="bg-slate-50 border border-slate-200/80 rounded-2xl p-4">
                      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                        Historical Low
                      </span>
                      <span className="text-2xl font-black text-emerald-600 block mt-1">
                        {formatCurrency(historyData.lowest_recorded_price)}
                      </span>
                      <span className="text-[11px] text-slate-400 block">
                        On {historyData.lowest_recorded_date}
                      </span>
                    </div>

                    <div className="bg-slate-50 border border-slate-200/80 rounded-2xl p-4">
                      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                        Historical High
                      </span>
                      <span className="text-2xl font-black text-slate-900 block mt-1">
                        {formatCurrency(historyData.highest_recorded_price)}
                      </span>
                      <span className="text-[11px] text-slate-400 block">
                        On {historyData.highest_recorded_date}
                      </span>
                    </div>
                  </div>

                  {/* Chart Section */}
                  <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-4">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-bold text-slate-900">
                          Multi-Platform Historical Price Trajectory
                        </h3>
                        <p className="text-xs text-slate-400">
                          Recorded timestamps from scrape runs and partner store prices
                        </p>
                      </div>

                      {/* Time Range Pills */}
                      <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
                        {["ALL", "1W", "1M", "6M"].map((r) => (
                          <button
                            key={r}
                            onClick={() => handleRangeChange(r)}
                            className={`px-3 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                              selectedRange === r
                                ? "bg-white text-slate-900 shadow-2xs"
                                : "text-slate-500 hover:text-slate-900"
                            }`}
                          >
                            {r}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Recharts Multi-Line Graph */}
                    <div className="h-72 w-full pt-2">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart
                          data={historyData.history_points}
                          margin={{ top: 10, right: 20, left: 10, bottom: 5 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                          <XAxis
                            dataKey="date"
                            tick={{ fontSize: 11, fill: "#64748b" }}
                            stroke="#cbd5e1"
                          />
                          <YAxis
                            tick={{ fontSize: 11, fill: "#64748b" }}
                            stroke="#cbd5e1"
                            tickFormatter={(v) => `₹${v}`}
                            domain={["auto", "auto"]}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: "white",
                              border: "1px solid #e2e8f0",
                              borderRadius: "12px",
                              boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
                              fontSize: "12px",
                            }}
                            formatter={(value: any, name?: any) => [
                              `₹${Number(value).toLocaleString("en-IN")}`,
                              String(name || "").toUpperCase(),
                            ]}
                          />
                          <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "10px" }} />

                          {/* Line for each available platform */}
                          {Object.keys(platformColors).map((platKey) => {
                            const hasPlatData = historyData.history_points.some(
                              (pt) => pt[platKey] !== undefined && pt[platKey] !== null
                            );
                            if (!hasPlatData) return null;

                            return (
                              <Line
                                key={platKey}
                                type="monotone"
                                dataKey={platKey}
                                name={platKey}
                                stroke={platformColors[platKey]}
                                strokeWidth={2.5}
                                dot={{ r: 4, strokeWidth: 1.5, fill: "#fff" }}
                                activeDot={{ r: 6 }}
                              />
                            );
                          })}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  {/* Platform Price Breakdown Cards */}
                  <div className="space-y-3">
                    <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                      Platform Breakdown & Lowest Historical Records
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                      {historyData.platform_stats.map((pStat) => (
                        <div
                          key={pStat.platform}
                          className="bg-slate-50 border border-slate-200/90 rounded-2xl p-4 space-y-2"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <PlatformLogo platform={pStat.platform} className="h-4 w-auto max-w-16" />
                              <span className="text-xs font-bold text-slate-800">{pStat.platform_name}</span>
                            </div>
                            <span className="text-sm font-black text-slate-900">
                              {formatCurrency(pStat.current_price)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between text-xs text-slate-500 pt-1 border-t border-slate-200/60">
                            <span>Historical Low:</span>
                            <span className="font-bold text-emerald-600">{formatCurrency(pStat.lowest_price)}</span>
                          </div>
                          <div className="flex items-center justify-between text-xs text-slate-500">
                            <span>Historical High:</span>
                            <span className="font-semibold text-slate-700">{formatCurrency(pStat.highest_price)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              ) : null}
            </div>

            {/* Modal Footer */}
            <div className="p-4 sm:px-6 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <button
                onClick={() => navigate(`/products/${encodeURIComponent(modalProduct.family_id)}`)}
                className="px-5 py-2.5 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs font-bold rounded-xl transition-colors flex items-center justify-center gap-2 cursor-pointer shadow-xs"
              >
                <span>Compare All 7 Platforms For This Product</span>
                <ArrowRight className="w-4 h-4" />
              </button>
              <button
                onClick={closeGraphModal}
                className="px-5 py-2.5 bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 text-xs font-bold rounded-xl transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AnalysisPage;
