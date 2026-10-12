import React, { useState, useEffect } from "react";
import {
  Activity,
  Server,
  RotateCw,
  FileText,
  Clock,
  CheckCircle2,
  AlertCircle,
  Database,
  Cpu,
} from "lucide-react";
import scraperService from "../services/scraperService";
import { RecentRun } from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";

interface HealthData {
  status: string;
  service: string;
  timestamp: string;
  database: string;
  pipeline_running: boolean;
  latency_ms: number;
  endpoint: string;
}

export const SystemStatusPage: React.FC = () => {
  const [recentRuns, setRecentRuns] = useState<RecentRun[]>([]);
  const [isLoadingRuns, setIsLoadingRuns] = useState<boolean>(true);
  const [selectedLogRun, setSelectedLogRun] = useState<RecentRun | null>(null);

  // Live FastAPI Health State
  const [healthData, setHealthData] = useState<HealthData | null>(null);
  const [isHealthChecking, setIsHealthChecking] = useState<boolean>(false);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  const pingHealth = async () => {
    setIsHealthChecking(true);
    setHealthError(null);
    try {
      const data = await scraperService.checkHealth();
      setHealthData(data);
      setLastChecked(new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    } catch (err: any) {
      setHealthError(err.message || "Failed to reach FastAPI backend");
      setHealthData(null);
    } finally {
      setIsHealthChecking(false);
    }
  };

  const loadRuns = async () => {
    setIsLoadingRuns(true);
    try {
      const runs = await scraperService.getRecentRuns();
      setRecentRuns(runs || []);
    } catch {
      setRecentRuns([]);
    } finally {
      setIsLoadingRuns(false);
    }
  };

  useEffect(() => {
    pingHealth();
    loadRuns();
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-8 py-8 space-y-6">
      {/* Page Heading & Action Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
            Platform Scraper Monitoring
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 font-medium mt-0.5">
            Live database execution records and real-time FastAPI service telemetry.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              pingHealth();
              loadRuns();
            }}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-bold transition-all shadow-2xs cursor-pointer"
          >
            <RotateCw className={`w-3.5 h-3.5 ${isLoadingRuns || isHealthChecking ? "animate-spin text-sky-600" : ""}`} />
            <span>Refresh All</span>
          </button>
        </div>
      </div>

      {/* Real FastAPI Server Health Box (Full-width long box with real telemetry) */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-2xs p-5 sm:p-6 transition-all">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-slate-100">
          <div className="flex items-center gap-3.5">
            <div className={`w-11 h-11 rounded-2xl flex items-center justify-center border transition-colors ${
              healthData
                ? "bg-emerald-50 text-emerald-600 border-emerald-200"
                : healthError
                ? "bg-rose-50 text-rose-600 border-rose-200"
                : "bg-slate-50 text-slate-500 border-slate-200"
            }`}>
              <Server className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-extrabold text-base text-slate-900">
                  {healthData?.service || "FastAPI Core Application Server"}
                </h3>
                <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-2 py-0.5 rounded-md font-bold">
                  /api/health
                </span>
              </div>
              <p className="text-xs text-slate-500 font-medium mt-0.5">
                Live backend health probe with round-trip latency &amp; Supabase persistence status
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 self-start md:self-auto">
            {healthData ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                ONLINE (200 OK)
              </span>
            ) : healthError ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-rose-50 text-rose-700 border border-rose-200">
                <AlertCircle className="w-3.5 h-3.5 text-rose-600" />
                UNREACHABLE
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-slate-100 text-slate-600">
                CHECKING...
              </span>
            )}

            <button
              onClick={pingHealth}
              disabled={isHealthChecking}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-slate-900 hover:bg-slate-800 disabled:bg-slate-300 text-white text-xs font-bold transition-all shadow-2xs cursor-pointer"
            >
              <Activity className={`w-3.5 h-3.5 ${isHealthChecking ? "animate-pulse" : ""}`} />
              <span>{isHealthChecking ? "Pinging..." : "Ping Health Now"}</span>
            </button>
          </div>
        </div>

        {/* Real Live Telemetry Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-5 text-xs">
          <div className="p-3 bg-slate-50/80 rounded-xl border border-slate-100">
            <span className="text-slate-400 font-medium block text-[11px]">Round-Trip Latency</span>
            <div className="font-extrabold text-sm text-slate-900 mt-1 font-mono flex items-center gap-1.5">
              <span className={healthData && healthData.latency_ms < 300 ? "text-emerald-600" : "text-amber-600"}>
                {healthData ? `${healthData.latency_ms} ms` : "—"}
              </span>
            </div>
          </div>

          <div className="p-3 bg-slate-50/80 rounded-xl border border-slate-100">
            <span className="text-slate-400 font-medium block text-[11px]">Supabase Persistence</span>
            <div className="font-extrabold text-sm text-slate-900 mt-1 flex items-center gap-1.5">
              <Database className="w-3.5 h-3.5 text-sky-500" />
              <span className="capitalize">{healthData?.database || (healthError ? "Unavailable" : "Connecting...")}</span>
            </div>
          </div>

          <div className="p-3 bg-slate-50/80 rounded-xl border border-slate-100">
            <span className="text-slate-400 font-medium block text-[11px]">Pipeline Status</span>
            <div className="font-extrabold text-sm text-slate-900 mt-1 flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-indigo-500" />
              <span>{healthData?.pipeline_running ? "Scraper Active" : "Idle (Ready)"}</span>
            </div>
          </div>

          <div className="p-3 bg-slate-50/80 rounded-xl border border-slate-100">
            <span className="text-slate-400 font-medium block text-[11px]">Last Ping Timestamp</span>
            <div className="font-extrabold text-sm text-slate-900 mt-1 font-mono">
              {lastChecked || "Checking..."}
            </div>
          </div>
        </div>

        {healthError && (
          <div className="mt-4 p-3 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 text-xs font-semibold">
            Server ping failed: {healthError}
          </div>
        )}
      </div>

      {/* Database Scraper Runs Table (Directly from Supabase scrape_runs) */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-2xs overflow-hidden">
        <div className="p-5 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Database className="w-5 h-5 text-sky-500" />
            <div>
              <h2 className="font-extrabold text-base text-slate-900">
                Scraper Runs Database Table
              </h2>
              <span className="text-[11px] text-slate-400 font-medium">
                Live records stored in Supabase <code className="font-mono text-slate-600 bg-slate-100 px-1 py-0.5 rounded">scrape_runs</code>
              </span>
            </div>
          </div>
          <span className="text-xs font-bold text-slate-500 bg-slate-50 border border-slate-200 px-3 py-1 rounded-xl">
            {recentRuns.length} Runs Recorded
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4">Platform</th>
                <th className="py-3 px-4">Job / Run ID</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Products Fetched</th>
                <th className="py-3 px-4">Duration</th>
                <th className="py-3 px-4 text-right">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-medium text-slate-700">
              {isLoadingRuns ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    <RotateCw className="w-5 h-5 animate-spin mx-auto mb-2 text-sky-600" />
                    Loading scraper execution records from database...
                  </td>
                </tr>
              ) : recentRuns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    No scraper runs found in the database.
                  </td>
                </tr>
              ) : (
                recentRuns.map((r, idx) => (
                  <tr key={idx} className="hover:bg-slate-50/60 transition-colors">
                    <td className="py-3.5 px-4 text-slate-600 font-mono text-[11px]">
                      {r.timestamp}
                    </td>
                    <td className="py-3.5 px-4 font-bold text-slate-900 text-xs">
                      {r.platform}
                    </td>
                    <td className="py-3.5 px-4 font-mono text-slate-500 text-[11px]">
                      {r.job_id}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${
                        r.status.toLowerCase() === "completed"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : r.status.toLowerCase() === "running"
                          ? "bg-sky-50 text-sky-700 border-sky-200"
                          : "bg-rose-50 text-rose-700 border-rose-200"
                      }`}>
                        <span>
                          {r.status.toLowerCase() === "completed"
                            ? "✅"
                            : r.status.toLowerCase() === "running"
                            ? "⚡"
                            : "❌"}
                        </span>
                        <span>{r.status.toUpperCase()}</span>
                      </span>
                    </td>
                    <td className="py-3.5 px-4 font-mono font-bold text-slate-900">
                      {r.products_fetched.toLocaleString("en-IN")}
                    </td>
                    <td className="py-3.5 px-4 font-mono text-slate-500">
                      {r.duration}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <button
                        onClick={() => setSelectedLogRun(r)}
                        className="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold inline-flex items-center gap-1 cursor-pointer transition-colors"
                      >
                        <FileText className="w-3 h-3 text-slate-500" />
                        <span>View</span>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Run Details Modal */}
      {selectedLogRun && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <PlatformLogo platform={selectedLogRun.platform} size="sm" />
                <h4 className="font-extrabold text-slate-900 text-sm">
                  Run Details: {selectedLogRun.platform} ({selectedLogRun.job_id})
                </h4>
              </div>
              <button
                onClick={() => setSelectedLogRun(null)}
                className="text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="p-4 bg-slate-900 rounded-xl font-mono text-xs text-emerald-400 space-y-1.5">
              <div>[TIMESTAMP] {selectedLogRun.timestamp}</div>
              <div>[PLATFORM] {selectedLogRun.platform}</div>
              <div>[STATUS] {selectedLogRun.status}</div>
              <div>[PRODUCTS] {selectedLogRun.products_fetched.toLocaleString("en-IN")} items stored</div>
              <div>[DURATION] {selectedLogRun.duration}</div>
              <div className="text-slate-300 pt-1 border-t border-slate-800">[MESSAGE] {selectedLogRun.message}</div>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() => setSelectedLogRun(null)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-xl cursor-pointer"
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

export default SystemStatusPage;
