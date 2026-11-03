import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Sparkles,
  ExternalLink,
  ArrowRight,
  Maximize2,
  Minimize2,
  RefreshCw,
  SlidersHorizontal,
  RotateCw,
  Calendar,
} from "lucide-react";
import analyticsService from "../services/analyticsService";
import bundleService from "../services/bundleService";
import {
  AnalyticsProductRow,
  AnalyticsPlatformPrice,
} from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";

export const AnalysisPage: React.FC = () => {
  const navigate = useNavigate();

  // Filter & list state
  const [products, setProducts] = useState<AnalyticsProductRow[]>([]);
  const [totalRecords, setTotalRecords] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);
  const [isLoadingList, setIsLoadingList] = useState<boolean>(true);

  // Scrape comparison state
  const [targetDate, setTargetDate] = useState<string>("");
  const [previousDate, setPreviousDate] = useState<string>("");
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [changesOnly, setChangesOnly] = useState<boolean>(true);
  const [totalDrops, setTotalDrops] = useState<number>(0);
  const [totalRises, setTotalRises] = useState<number>(0);
  const [isSyncingTelemetry, setIsSyncingTelemetry] = useState<boolean>(false);

  // Filters & Search
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [category, setCategory] = useState<string>("All");
  const [platform, setPlatform] = useState<string>("All");
  const [sortBy, setSortBy] = useState<string>("price_change");

  // Expandable row state (similar to View Data)
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  // Fullscreen table toggle
  const [isFullscreenTable, setIsFullscreenTable] = useState<boolean>(false);

  const formatDateLabel = (dateStr?: string | null) => {
    if (!dateStr) return "Latest Scrape";
    try {
      const parts = dateStr.split("-");
      if (parts.length === 3) {
        const year = parseInt(parts[0], 10);
        const monthIndex = parseInt(parts[1], 10) - 1;
        const day = parseInt(parts[2], 10);
        const d = new Date(year, monthIndex, day);
        return d.toLocaleDateString("en-IN", {
          day: "numeric",
          month: "short",
          year: "numeric",
        });
      }
    } catch {}
    return dateStr;
  };

  const formatCurrency = (val?: number | null) => {
    if (val === null || val === undefined) return "—";
    return `₹${Math.round(val).toLocaleString("en-IN")}`;
  };

  // Load available scrape dates on mount
  useEffect(() => {
    analyticsService.getAvailableDates().then((res) => {
      if (res.available_dates && res.available_dates.length > 0) {
        setAvailableDates(res.available_dates);
      }
    }).catch(() => null);
  }, []);

  // Reload when filters change
  useEffect(() => {
    loadProductList(1);
  }, [category, platform, sortBy, changesOnly, targetDate]);

  const loadProductList = async (
    pageToLoad: number = 1,
    overrideChangesOnly?: boolean
  ) => {
    setIsLoadingList(true);
    const activeChangesOnly = overrideChangesOnly !== undefined ? overrideChangesOnly : changesOnly;

    try {
      const data = await analyticsService.getProducts({
        target_date: targetDate || undefined,
        changes_only: activeChangesOnly,
        category: category !== "All" ? category : undefined,
        platform: platform !== "All" ? platform : undefined,
        sort_by: sortBy,
        search: searchTerm.trim() || undefined,
        page: pageToLoad,
        page_size: pageSize,
      });

      setProducts(data.products || []);
      setTotalRecords(data.total_records || 0);
      setTotalPages(data.total_pages || 1);
      setCurrentPage(data.page || 1);
      if (data.target_date) setTargetDate(data.target_date);
      if (data.previous_date) setPreviousDate(data.previous_date);
      if (data.total_price_drops !== undefined) setTotalDrops(data.total_price_drops);
      if (data.total_price_rises !== undefined) setTotalRises(data.total_price_rises);
    } catch (err) {
      console.error("Failed to load analytics products", err);
    } finally {
      setIsLoadingList(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadProductList(1);
  };

  const handleSyncTelemetry = async () => {
    setIsSyncingTelemetry(true);
    try {
      await analyticsService.syncTelemetry();
      await loadProductList(1);
    } catch (err) {
      console.error("Telemetry sync failed", err);
    } finally {
      setIsSyncingTelemetry(false);
    }
  };

  const toggleExpand = (familyId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedRowId((prev) => (prev === familyId ? null : familyId));
  };

  return (
    <div className="h-full flex flex-col overflow-hidden max-w-7xl w-full mx-auto px-4 sm:px-8 py-3 space-y-3">
      {/* Page Title & Count */}
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
          Real selling price shifts compared strictly between current and previous scrapes across all platforms.
        </p>
      </div>

      {/* SCRAPE COMPARISON BAR (Simplified: Previous Scrape vs Current Changes) */}
      <div className="shrink-0 bg-gradient-to-r from-sky-50/80 via-white to-slate-50 border border-sky-100 rounded-2xl p-3 shadow-2xs flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Comparison Status Badge & Date Filter */}
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white border border-sky-200 shadow-2xs text-xs">
            <Calendar className="w-3.5 h-3.5 text-[#079FE0]" />
            <span className="font-bold text-slate-500">Date:</span>
            {availableDates.length > 0 ? (
              <div className="relative">
                <select
                  value={targetDate}
                  onChange={(e) => {
                    const sel = e.target.value;
                    setTargetDate(sel);
                  }}
                  className="appearance-none bg-sky-50/80 border border-sky-200 text-slate-900 rounded-lg pl-2 pr-6 py-0.5 text-xs font-black focus:outline-none focus:ring-1 focus:ring-[#079FE0] cursor-pointer"
                >
                  {availableDates.map((d) => (
                    <option key={d} value={d}>
                      {formatDateLabel(d)}
                    </option>
                  ))}
                </select>
                <ChevronDown className="w-3 h-3 text-slate-400 absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              </div>
            ) : (
              <span className="font-extrabold text-slate-900">
                {formatDateLabel(targetDate)}
              </span>
            )}
            <span className="text-slate-400 font-bold">vs prev:</span>
            <span className="font-bold text-slate-600">
              {formatDateLabel(previousDate)}
            </span>
          </div>

          {/* Changed Prices Only Toggle */}
          <button
            type="button"
            onClick={() => {
              const nextState = !changesOnly;
              setChangesOnly(nextState);
              loadProductList(1, nextState);
            }}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer border shadow-2xs ${
              changesOnly
                ? "bg-[#079FE0] text-white border-[#079FE0]"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
            }`}
          >
            <SlidersHorizontal className="w-3 h-3" />
            <span>Only Changed Prices ({totalRecords})</span>
          </button>
        </div>

        {/* Drops & Rises Summary Counters + Sync */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1.5 text-[11px] font-bold">
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
              <TrendingDown className="w-3 h-3" />
              {totalDrops} Drops
            </span>
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-rose-50 text-rose-700 border border-rose-200">
              <TrendingUp className="w-3 h-3" />
              {totalRises} Rises
            </span>
          </div>

          <button
            type="button"
            onClick={handleSyncTelemetry}
            disabled={isSyncingTelemetry}
            className="p-1.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 transition-colors disabled:opacity-50 cursor-pointer shadow-2xs"
            title="Sync latest scrape telemetry"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isSyncingTelemetry ? "animate-spin text-[#079FE0]" : ""}`} />
          </button>
        </div>
      </div>

      {/* FILTER & SEARCH BAR */}
      <div className="shrink-0 bg-white rounded-2xl border border-slate-200/90 p-3 shadow-2xs flex flex-wrap items-center justify-between gap-3">
        {/* Search */}
        <form onSubmit={handleSearchSubmit} className="flex-1 min-w-[220px] max-w-md relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search by title, style code, SKU..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-semibold text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0] transition-all"
          />
        </form>

        {/* Dropdowns */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Category */}
          <div className="relative">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 text-slate-700 rounded-xl px-3 py-1.5 pr-7 text-xs font-bold focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 cursor-pointer"
            >
              <option value="All">All Categories</option>
              <option value="Apparel">Apparel</option>
              <option value="Footwear">Footwear</option>
              <option value="Accessories">Accessories</option>
              <option value="Equipment">Equipment</option>
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* Platform */}
          <div className="relative">
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 text-slate-700 rounded-xl px-3 py-1.5 pr-7 text-xs font-bold focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 cursor-pointer"
            >
              <option value="All">All Platforms</option>
              <option value="amazon">Amazon</option>
              <option value="myntra">Myntra</option>
              <option value="ajio">AJIO</option>
              <option value="columbia">Columbia</option>
              <option value="adv">Adventuras</option>
              <option value="tata">Tata CLiQ</option>
              <option value="tata_lux">Tata CLiQ Luxury</option>
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* Sort */}
          <div className="relative">
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 text-slate-700 rounded-xl px-3 py-1.5 pr-7 text-xs font-bold focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 cursor-pointer"
            >
              <option value="price_change">Price Movements</option>
              <option value="price_asc">Price: Low to High</option>
              <option value="price_desc">Price: High to Low</option>
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

      {/* MAIN PRODUCT PRICE ANALYSIS TABLE */}
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

        {/* Table Header (Price Shift % column removed) */}
        <div className="shrink-0 p-3.5 sm:px-6 bg-slate-50/80 border-b border-slate-200/80 flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
          <div className="flex-1">Product &amp; Style Code</div>
          <div className="w-28 text-center hidden md:block">Platforms</div>
          <div className="w-32 text-right">Previous Scrape Price</div>
          <div className="w-32 text-right">Current Price</div>
          <div className="w-36 text-right">Actions</div>
        </div>

        {/* Scrollable Component Body */}
        <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {isLoadingList ? (
            <div className="py-24 text-center space-y-3">
              <div className="w-8 h-8 border-3 border-sky-200 border-t-[#079FE0] rounded-full animate-spin mx-auto" />
              <p className="text-xs font-semibold text-slate-500">Querying verified price movements across scrapes...</p>
            </div>
          ) : products.length === 0 ? (
            <div className="py-20 text-center space-y-3 max-w-md mx-auto px-4">
              <Sparkles className="w-8 h-8 text-[#079FE0] mx-auto" />
              <h3 className="font-bold text-slate-800 text-sm">No Price Changes Found</h3>
              <p className="text-xs text-slate-500 leading-relaxed">
                No selling price shifts were detected between the current and previous scrape for active filters. Try un-ticking "Only Changed Prices" to view all catalogue listings.
              </p>
            </div>
          ) : (
            products.map((prod) => {
              const isExpanded = expandedRowId === prod.family_id;
              const hasMultiplePlatforms = prod.platforms && prod.platforms.length > 0;
              const firstUrl = prod.platforms?.find((p) => p.url)?.url;

              return (
                <div key={prod.family_id} className="transition-colors hover:bg-slate-50/60">
                  {/* Main Product Row */}
                  <div
                    onClick={() => navigate(`/analysis/${encodeURIComponent(prod.family_id)}`)}
                    className="p-3.5 sm:px-6 flex items-center justify-between gap-4 cursor-pointer group hover:bg-sky-50/50"
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
                        <h3 className="text-xs sm:text-sm font-bold text-slate-900 hover:text-[#079FE0] transition-colors line-clamp-1">
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
                            {prod.platforms_count || prod.platforms?.length || 1} platforms
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Platforms Pill Preview (Direct links where available) */}
                    <div className="w-28 text-center hidden md:flex items-center justify-center gap-1 shrink-0 flex-wrap">
                      {(prod.platforms || []).slice(0, 4).map((plat) => (
                        <span
                          key={plat.platform}
                          title={`${plat.platform_name}: ${formatCurrency(plat.price)}`}
                          className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                            plat.is_changed
                              ? "bg-amber-100 text-amber-800 border border-amber-300"
                              : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {plat.platform_name}
                        </span>
                      ))}
                      {(prod.platforms?.length || 0) > 4 && (
                        <span className="text-[9px] text-slate-400 font-bold">
                          +{prod.platforms!.length - 4}
                        </span>
                      )}
                    </div>

                    {/* Previous Price */}
                    <div className="w-32 text-right shrink-0">
                      <span className="text-xs font-bold text-slate-700 block">
                        {prod.previous_price && prod.previous_price > 0
                          ? formatCurrency(prod.previous_price)
                          : "—"}
                      </span>
                      <span className="text-[10px] text-slate-400 font-medium block">
                        {prod.change_platform ? `${prod.change_platform.toUpperCase()} Prior` : "Previous Scrape"}
                      </span>
                    </div>

                    {/* Current Scrape Price */}
                    <div className="w-32 text-right shrink-0">
                      <span className="text-sm font-black text-slate-900 block">
                        {formatCurrency(prod.lowest_price)}
                      </span>
                      <span className="text-[10px] font-bold text-[#079FE0] uppercase tracking-wider block">
                        Current Scrape
                      </span>
                    </div>

                    {/* Actions: View History & Graph on dedicated page */}
                    <div className="w-36 text-right shrink-0 flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        onClick={() => navigate(`/analysis/${encodeURIComponent(prod.family_id)}`)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs font-bold rounded-xl transition-all shadow-2xs cursor-pointer"
                        title="Open full price trajectory and history graph"
                      >
                        <span>View Graph</span>
                        <ArrowRight className="w-3 h-3" />
                      </button>

                      <button
                        type="button"
                        onClick={(e) => toggleExpand(prod.family_id, e)}
                        className="p-1 text-slate-400 hover:text-sky-600 transition-colors"
                        title={isExpanded ? "Collapse platform preview" : "Quick preview platforms"}
                      >
                        {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  {/* Expanded Platform Breakdown (Showing ALL Platforms even if price didn't change) */}
                  {isExpanded && (
                    <div className="px-4 sm:px-6 py-4 bg-sky-50/40 border-t border-sky-100 space-y-3 animate-in fade-in">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                          Platform Prices &amp; Direct Store Links ({prod.platforms?.length || 0} active stores)
                        </span>
                        <span className="text-[11px] text-slate-400">
                          Showing all available platforms recorded for this style
                        </span>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        {(prod.platforms || []).map((plat) => {
                          const hasChanged = plat.is_changed;
                          return (
                            <div
                              key={plat.platform}
                              className={`p-3 bg-white rounded-xl border space-y-2 shadow-2xs ${
                                hasChanged ? "border-amber-300 ring-1 ring-amber-200" : "border-slate-200/80"
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-extrabold text-xs text-slate-900">
                                  {plat.platform_name}
                                </span>
                                {hasChanged && (
                                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                                    Price Shift
                                  </span>
                                )}
                              </div>

                              {/* Current vs Previous Price */}
                              <div className="flex items-baseline justify-between">
                                <div>
                                  <div className="text-[10px] text-slate-400 uppercase font-semibold">Current</div>
                                  <div className="font-black text-sm text-slate-900">
                                    {formatCurrency(plat.price)}
                                  </div>
                                </div>
                                <div className="text-right">
                                  <div className="text-[10px] text-slate-400 uppercase font-semibold">Previous</div>
                                  <div className="font-bold text-xs text-slate-600">
                                    {formatCurrency(plat.previous_price)}
                                  </div>
                                </div>
                              </div>

                              {/* Status & Open Link */}
                              <div className="pt-1 border-t border-slate-100 flex items-center justify-between text-[11px]">
                                <span className="text-emerald-700 font-semibold text-[10px]">
                                  {plat.availability_status || "In stock"}
                                </span>

                                {plat.url ? (
                                  <a
                                    href={plat.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    onClick={(e) => e.stopPropagation()}
                                    className="inline-flex items-center gap-1 text-[#079FE0] hover:text-[#068ec8] font-bold text-[11px] hover:underline"
                                  >
                                    <span>Open Store</span>
                                    <ExternalLink className="w-3 h-3" />
                                  </a>
                                ) : (
                                  <span className="text-slate-300 italic text-[10px]">No direct link</span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Pagination Bar */}
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
    </div>
  );
};

export default AnalysisPage;
