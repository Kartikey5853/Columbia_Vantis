import React, { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
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
  ArrowLeft,
  ExternalLink,
  Calendar,
  Layers,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Tag,
  Store,
  LineChart as LineChartIcon,
  RefreshCw,
  Clock,
  CheckCircle2,
} from "lucide-react";
import analyticsService from "../services/analyticsService";
import { ProductPriceHistoryResponse, PlatformPriceStat } from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";

const PLATFORM_COLORS: Record<string, string> = {
  amazon: "#FF9900",
  myntra: "#FF3F6C",
  ajio: "#2C4152",
  columbia: "#079FE0",
  adv: "#10B981",
  tata: "#E40046",
  tata_lux: "#8B5CF6",
};

export const AnalysisProductDetailsPage: React.FC = () => {
  const { familyId } = useParams<{ familyId: string }>();
  const navigate = useNavigate();

  const [historyData, setHistoryData] = useState<ProductPriceHistoryResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRange, setSelectedRange] = useState<string>("ALL");
  const [activePlatformFilter, setActivePlatformFilter] = useState<string>("ALL");

  useEffect(() => {
    if (familyId) {
      loadHistory(familyId, selectedRange);
    }
  }, [familyId]);

  const loadHistory = async (id: string, range: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await analyticsService.getPriceHistory(id, range);
      setHistoryData(data);
    } catch (err) {
      console.error("Failed to load product price telemetry", err);
      setError("Could not load price telemetry for this product.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleRangeChange = (r: string) => {
    setSelectedRange(r);
    if (familyId) {
      loadHistory(familyId, r);
    }
  };

  const formatCurrency = (val?: number | null) => {
    if (val === null || val === undefined) return "—";
    return `₹${Math.round(val).toLocaleString("en-IN")}`;
  };

  // Build flattened history rows for the daily scrape log table
  const flattenedHistoryRows = useMemo(() => {
    if (!historyData || !historyData.history_points) return [];
    const rows: Array<{
      date: string;
      rawDate: string;
      platform: string;
      platformName: string;
      price: number;
      currentPrice: number;
      diff: number;
      url?: string | null;
    }> = [];

    const statsMap: Record<string, PlatformPriceStat> = {};
    (historyData.platform_stats || []).forEach((ps) => {
      statsMap[ps.platform] = ps;
    });

    historyData.history_points.forEach((pt) => {
      const d = pt.date;
      const rawDate = pt.raw_date || pt.date;
      Object.keys(pt).forEach((k) => {
        if (k !== "date" && k !== "raw_date" && pt[k] !== null && pt[k] !== undefined) {
          const price = Number(pt[k]);
          const ps = statsMap[k];
          const curr = ps?.current_price || price;
          const diff = price - curr;
          if (activePlatformFilter === "ALL" || activePlatformFilter === k) {
            rows.push({
              date: d,
              rawDate,
              platform: k,
              platformName: ps?.platform_name || k.toUpperCase(),
              price,
              currentPrice: curr,
              diff,
              url: ps?.url,
            });
          }
        }
      });
    });

    return rows.reverse();
  }, [historyData, activePlatformFilter]);

  // Filtered platforms to display on graph
  const displayedPlatforms = useMemo(() => {
    if (!historyData?.platform_stats) return [];
    if (activePlatformFilter === "ALL") return historyData.platform_stats;
    return historyData.platform_stats.filter((ps) => ps.platform === activePlatformFilter);
  }, [historyData, activePlatformFilter]);

  if (isLoading) {
    return (
      <div className="h-full flex flex-col items-center justify-center space-y-3 p-8">
        <div className="w-10 h-10 border-3 border-sky-200 border-t-[#079FE0] rounded-full animate-spin" />
        <p className="text-xs font-semibold text-slate-500">
          Loading full historical price telemetry &amp; days scraped...
        </p>
      </div>
    );
  }

  if (error || !historyData) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center space-y-4">
        <h2 className="text-lg font-black text-slate-800">Telemetry Record Not Found</h2>
        <p className="text-xs text-slate-500 leading-relaxed max-w-md mx-auto">
          {error || "Price history telemetry points have not been indexed for this item yet."}
        </p>
        <button
          onClick={() => navigate("/analysis")}
          className="inline-flex items-center gap-2 px-4 py-2 bg-[#079FE0] text-white text-xs font-bold rounded-xl shadow-xs hover:bg-[#068ec8] transition-all cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Price Movements</span>
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-7xl w-full mx-auto px-4 sm:px-8 py-5 space-y-6">
      {/* Top Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate("/analysis")}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-bold transition-all shadow-2xs cursor-pointer group"
        >
          <ArrowLeft className="w-3.5 h-3.5 text-slate-400 group-hover:text-slate-800 transition-colors" />
          <span>Back to Price Movements</span>
        </button>

        <div className="text-xs text-slate-400 font-semibold flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5 text-[#079FE0]" />
          <span>All Days Scraped Historical Trajectory</span>
        </div>
      </div>

      {/* Product Hero Info Card */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-2xs p-5 sm:p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div className="flex items-center gap-4 min-w-0 flex-1">
          <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-2xl bg-slate-50 border border-slate-100 p-2 shrink-0 flex items-center justify-center overflow-hidden">
            <img
              src={historyData.image_url || "/vantis_logo.png"}
              alt={historyData.title}
              className="w-full h-full object-contain"
              onError={(e) => {
                (e.target as HTMLImageElement).src = "/vantis_logo.png";
              }}
            />
          </div>

          <div className="min-w-0 space-y-1.5">
            <h1 className="text-base sm:text-xl font-black text-slate-900 leading-snug">
              {historyData.title}
            </h1>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {historyData.style && (
                <span className="font-mono font-bold text-slate-700 bg-slate-100 px-2 py-0.5 rounded-md text-[11px]">
                  {historyData.style}
                </span>
              )}
              {historyData.ean && (
                <span className="font-mono text-slate-400 text-[11px]">
                  EAN: {historyData.ean}
                </span>
              )}
              <span className="text-slate-400 font-medium text-[11px]">
                {historyData.category} • {historyData.gender}
              </span>
              <span className="text-[#079FE0] font-bold text-[11px] bg-sky-50 px-2 py-0.5 rounded-md border border-sky-100">
                {historyData.platform_stats?.length || 1} platforms tracked
              </span>
            </div>
          </div>
        </div>

        {/* Price Telemetry Summary Badges */}
        <div className="flex flex-wrap md:flex-nowrap items-center gap-3 shrink-0 self-stretch md:self-center">
          <div className="p-3 bg-slate-50 rounded-2xl border border-slate-200/80 min-w-[120px] text-right">
            <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider block">
              Current Lowest
            </span>
            <span className="text-base sm:text-lg font-black text-slate-900 block">
              {formatCurrency(historyData.current_price)}
            </span>
          </div>

          <div className="p-3 bg-emerald-50/70 rounded-2xl border border-emerald-200/80 min-w-[120px] text-right">
            <span className="text-[10px] text-emerald-700 font-bold uppercase tracking-wider block">
              All-Time Low
            </span>
            <span className="text-base sm:text-lg font-black text-emerald-700 block">
              {formatCurrency(historyData.lowest_recorded_price)}
            </span>
            <span className="text-[9px] text-emerald-600 font-medium">
              on {historyData.lowest_recorded_date}
            </span>
          </div>

          <div className="p-3 bg-slate-50 rounded-2xl border border-slate-200/80 min-w-[120px] text-right">
            <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider block">
              All-Time High
            </span>
            <span className="text-base sm:text-lg font-black text-slate-900 block">
              {formatCurrency(historyData.highest_recorded_price)}
            </span>
            <span className="text-[9px] text-slate-400 font-medium">
              on {historyData.highest_recorded_date}
            </span>
          </div>
        </div>
      </div>

      {/* INTERACTIVE GRAPH CONTAINER */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-2xs p-5 sm:p-6 space-y-4">
        {/* Graph Header & Platform Filter Switcher */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-slate-100">
          <div>
            <h2 className="text-base sm:text-lg font-black text-slate-900 flex items-center gap-2">
              <LineChartIcon className="w-5 h-5 text-[#079FE0]" />
              Multi-Platform Price Trajectory Across Scrapes
            </h2>
            <p className="text-xs text-slate-500 font-medium">
              Select platforms to isolate trajectories or view all platforms compared across every recorded day.
            </p>
          </div>

          {/* Range Controls */}
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl self-start md:self-center">
            {["1M", "3M", "6M", "1Y", "ALL"].map((r) => (
              <button
                key={r}
                type="button"
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

        {/* Platform Selector Buttons (Option to change platforms on graph) */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <span className="text-xs font-bold text-slate-500 mr-1 flex items-center gap-1">
            <Store className="w-3.5 h-3.5 text-[#079FE0]" />
            Filter Platform:
          </span>

          <button
            type="button"
            onClick={() => setActivePlatformFilter("ALL")}
            className={`px-3 py-1.5 rounded-xl text-xs font-extrabold transition-all cursor-pointer border ${
              activePlatformFilter === "ALL"
                ? "bg-slate-900 text-white border-slate-900 shadow-xs"
                : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
            }`}
          >
            All Platforms ({historyData.platform_stats?.length || 0})
          </button>

          {(historyData.platform_stats || []).map((ps) => {
            const isSelected = activePlatformFilter === ps.platform;
            const color = PLATFORM_COLORS[ps.platform] || "#64748B";
            return (
              <button
                key={ps.platform}
                type="button"
                onClick={() => setActivePlatformFilter(ps.platform)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer border ${
                  isSelected
                    ? "text-white shadow-xs"
                    : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                }`}
                style={{
                  backgroundColor: isSelected ? color : undefined,
                  borderColor: isSelected ? color : undefined,
                }}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: isSelected ? "#fff" : color }}
                />
                <span>{ps.platform_name}</span>
                <span className={`text-[10px] ${isSelected ? "text-white/80" : "text-slate-400"}`}>
                  {formatCurrency(ps.current_price)}
                </span>
              </button>
            );
          })}
        </div>

        {/* The Recharts Graph */}
        <div className="pt-2">
          {historyData.history_points && historyData.history_points.length > 0 ? (
            <div className="h-72 sm:h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={historyData.history_points}
                  margin={{ top: 10, right: 20, left: 10, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis
                    dataKey="date"
                    stroke="#94a3b8"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: "#e2e8f0" }}
                  />
                  <YAxis
                    stroke="#94a3b8"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: "#e2e8f0" }}
                    tickFormatter={(v) => `₹${Number(v).toLocaleString("en-IN")}`}
                    domain={["dataMin - 200", "dataMax + 200"]}
                  />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload || !payload.length) return null;
                      return (
                        <div className="bg-slate-900 text-white p-3 rounded-2xl shadow-xl text-xs space-y-1.5 border border-slate-800 min-w-[180px]">
                          <div className="font-bold text-sky-300 pb-1 border-b border-slate-800">
                            {label}
                          </div>
                          {payload.map((item: any) => {
                            const pName = item.name;
                            const price = item.value;
                            return (
                              <div
                                key={item.dataKey}
                                className="flex items-center justify-between gap-3 text-[11px]"
                              >
                                <span className="font-semibold text-slate-300 flex items-center gap-1.5">
                                  <span
                                    className="w-2 h-2 rounded-full"
                                    style={{ backgroundColor: item.color }}
                                  />
                                  {pName}:
                                </span>
                                <span className="font-mono font-bold text-white">
                                  ₹{Number(price).toLocaleString("en-IN")}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      );
                    }}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    iconType="circle"
                    wrapperStyle={{ fontSize: "11px", paddingBottom: "10px" }}
                  />

                  {/* Draw a line for each displayed platform */}
                  {displayedPlatforms.map((ps) => {
                    const color = PLATFORM_COLORS[ps.platform] || "#64748B";
                    return (
                      <Line
                        key={ps.platform}
                        type="monotone"
                        dataKey={ps.platform}
                        name={ps.platform_name}
                        stroke={color}
                        strokeWidth={2.5}
                        dot={{ r: 3, fill: color, strokeWidth: 1, stroke: "#fff" }}
                        activeDot={{ r: 6, fill: color, strokeWidth: 2, stroke: "#fff" }}
                        connectNulls
                      />
                    );
                  })}
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-48 flex flex-col items-center justify-center text-slate-500 space-y-2 p-6 bg-slate-50/50 rounded-2xl border border-slate-200/80">
              <LineChartIcon className="w-8 h-8 text-slate-400 stroke-1" />
              <p className="text-xs font-bold text-slate-800">Insufficient Telemetry Points</p>
              <p className="text-[11px] text-slate-400 text-center max-w-sm">
                Additional scrape runs will populate multi-point trajectories for this style.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* PLATFORM CARDS WITH DIRECT STORE LINKS */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-black text-slate-900 flex items-center gap-2">
            <Store className="w-4 h-4 text-[#079FE0]" />
            Tracked Platforms &amp; Live Store Links
          </h2>
          <span className="text-xs text-slate-400 font-semibold">
            Open the exact product listing on each marketplace directly from here
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {(historyData.platform_stats || []).map((ps) => {
            const color = PLATFORM_COLORS[ps.platform] || "#64748B";
            return (
              <div
                key={ps.platform}
                className="bg-white rounded-2xl border border-slate-200/90 shadow-2xs p-4 flex flex-col justify-between space-y-3 hover:border-sky-300 transition-all"
              >
                <div className="space-y-2">
                  {/* Platform Header */}
                  <div className="flex items-center justify-between">
                    <span className="font-black text-xs sm:text-sm text-slate-900 flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                      {ps.platform_name}
                    </span>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                      Tracked
                    </span>
                  </div>

                  {/* Prices */}
                  <div className="flex items-baseline justify-between pt-1">
                    <div>
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                        Current Price
                      </span>
                      <span className="text-base font-black text-slate-900 block">
                        {formatCurrency(ps.current_price)}
                      </span>
                    </div>

                    <div className="text-right">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                        Lowest Recorded
                      </span>
                      <span className="text-xs font-bold text-emerald-700 block">
                        {formatCurrency(ps.lowest_price)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Direct Store Link Button */}
                <div className="pt-2 border-t border-slate-100 flex items-center justify-between">
                  <span className="text-[10px] font-semibold text-slate-400">
                    Highest: {formatCurrency(ps.highest_price)}
                  </span>

                  {ps.url ? (
                    <a
                      href={ps.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs font-bold rounded-xl transition-all shadow-2xs"
                    >
                      <span>Open Link</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  ) : (
                    <span className="text-[10px] text-slate-300 italic">No link available</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ALL DAYS SCRAPED TELEMETRY LOG TABLE */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-2xs overflow-hidden space-y-0">
        <div className="p-4 sm:px-6 bg-slate-50/80 border-b border-slate-200/80 flex items-center justify-between">
          <div className="space-y-0.5">
            <h3 className="text-xs sm:text-sm font-black text-slate-900 flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#079FE0]" />
              Historical Scrape Checkpoints Log ({flattenedHistoryRows.length} entries)
            </h3>
            <p className="text-[11px] text-slate-500">
              Detailed list of all prices captured on every scrape run date for this product.
            </p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-700">
            <thead className="bg-slate-50/50 text-[11px] font-bold text-slate-500 uppercase tracking-wider border-b border-slate-100">
              <tr>
                <th className="py-3 px-4">Scrape Date</th>
                <th className="py-3 px-4">Platform</th>
                <th className="py-3 px-4 text-right">Recorded Price</th>
                <th className="py-3 px-4 text-right">Current Price</th>
                <th className="py-3 px-4 text-right">Net Shift</th>
                <th className="py-3 px-4 text-right">Store Link</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-medium">
              {flattenedHistoryRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    No historical scrape logs found for the selected platform filter.
                  </td>
                </tr>
              ) : (
                flattenedHistoryRows.map((r, idx) => {
                  const isDrop = r.diff < 0;
                  const isRise = r.diff > 0;
                  return (
                    <tr key={`${r.rawDate}-${r.platform}-${idx}`} className="hover:bg-slate-50/60 transition-colors">
                      <td className="py-3 px-4 font-bold text-slate-900">
                        {r.date}
                      </td>
                      <td className="py-3 px-4">
                        <span className="font-bold text-slate-800">
                          {r.platformName}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-black text-slate-900">
                        {formatCurrency(r.price)}
                      </td>
                      <td className="py-3 px-4 text-right font-semibold text-slate-600">
                        {formatCurrency(r.currentPrice)}
                      </td>
                      <td className="py-3 px-4 text-right">
                        {isDrop ? (
                          <span className="inline-flex items-center gap-1 font-bold text-emerald-700">
                            <TrendingDown className="w-3 h-3" />
                            {formatCurrency(Math.abs(r.diff))} lower
                          </span>
                        ) : isRise ? (
                          <span className="inline-flex items-center gap-1 font-bold text-rose-700">
                            <TrendingUp className="w-3 h-3" />
                            +{formatCurrency(r.diff)} higher
                          </span>
                        ) : (
                          <span className="text-slate-400 font-semibold">Unchanged</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right">
                        {r.url ? (
                          <a
                            href={r.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-[#079FE0] hover:text-[#068ec8] font-bold hover:underline"
                          >
                            <span>Open Store</span>
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        ) : (
                          <span className="text-slate-300 italic text-[10px]">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default AnalysisProductDetailsPage;
