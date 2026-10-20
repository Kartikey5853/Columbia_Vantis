import React, { useEffect, useState, useCallback, useRef } from "react";
import { Cpu, ShieldAlert, RefreshCw, Clock, Database, CheckCircle2, Square, Radio, AlertOctagon } from "lucide-react";
import scraperService from "../../services/scraperService";
import authService from "../../services/authService";

export const ScrapingLockModal: React.FC = () => {
  const [isScraping, setIsScraping] = useState<boolean>(false);
  const [wasScraping, setWasScraping] = useState<boolean>(false);
  const [isChecking, setIsChecking] = useState<boolean>(false);
  const [isStopping, setIsStopping] = useState<boolean>(false);
  const [customMsg, setCustomMsg] = useState<string>("");
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const timerRef = useRef<any>(null);

  const checkStatus = useCallback(async () => {
    try {
      setIsChecking(true);
      const res = await scraperService.checkHealth();
      const running = Boolean(res.pipeline_running);
      
      if (running) {
        setIsScraping(true);
        setWasScraping(true);
      } else if (isScraping) {
        // Scraper was active and now finished!
        setIsScraping(false);
      }
    } catch (e) {
      // In case backend is temporarily 503 or unreachable, keep state as is
    } finally {
      setIsChecking(false);
    }
  }, [isScraping]);

  useEffect(() => {
    // 1. Initial health check on mount
    checkStatus();

    // 2. Poll every 12 seconds
    const pollInterval = setInterval(() => {
      checkStatus();
    }, 12000);

    // 3. Listen to global 503 scrapers-active event from apiClient
    const handleScrapingEvent = (event: any) => {
      setIsScraping(true);
      setWasScraping(true);
      if (event?.detail?.message) {
        setCustomMsg(event.detail.message);
      }
    };

    window.addEventListener("vantis-scraping-active", handleScrapingEvent);

    return () => {
      clearInterval(pollInterval);
      window.removeEventListener("vantis-scraping-active", handleScrapingEvent);
    };
  }, [checkStatus]);

  // Elapsed timer while scraping is active
  useEffect(() => {
    if (isScraping) {
      document.body.style.overflow = "hidden";
      timerRef.current = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } else {
      document.body.style.overflow = "";
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      document.body.style.overflow = "";
    };
  }, [isScraping]);

  const handleStopScraper = async () => {
    const confirmStop = window.confirm("Are you sure you want to halt the active scraping pipeline?");
    if (!confirmStop) return;

    try {
      setIsStopping(true);
      await scraperService.stopScraper("Stopped by user via Scraping Lock Screen");
      await checkStatus();
    } catch (err: any) {
      alert("Failed to stop scraper: " + (err?.message || "Unknown error"));
    } finally {
      setIsStopping(false);
    }
  };

  const handleReload = () => {
    window.location.reload();
  };

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}m ${s < 10 ? "0" : ""}${s}s`;
  };

  // If currently not scraping and was never scraping during this session, do not render anything
  if (!isScraping && !wasScraping) {
    return null;
  }

  // Case 1: Scraping has just finished
  if (!isScraping && wasScraping) {
    return (
      <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/85 backdrop-blur-md p-4 animate-in fade-in duration-300">
        <div className="bg-white/95 backdrop-blur-xl border border-emerald-500/30 rounded-3xl p-8 max-w-lg w-full shadow-2xl text-center space-y-6">
          <div className="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center mx-auto shadow-inner">
            <CheckCircle2 className="w-9 h-9" />
          </div>

          <div className="space-y-2">
            <h2 className="text-2xl font-bold text-slate-900">Scraping Completed!</h2>
            <p className="text-sm text-slate-600 leading-relaxed">
              The scraper execution has completed successfully. Server RAM protection has been lifted and catalog access is fully restored.
            </p>
          </div>

          <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-4 text-xs text-emerald-800 space-y-1 text-left">
            <div className="font-semibold flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block animate-pulse"></span>
              All Systems Operational
            </div>
            <div>Latest product prices, stock, and offers are refreshed.</div>
          </div>

          <button
            onClick={handleReload}
            className="w-full py-3.5 px-6 rounded-2xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white font-semibold shadow-lg shadow-emerald-500/25 transition-all flex items-center justify-center gap-2 cursor-pointer"
          >
            <RefreshCw className="w-4 h-4" />
            Resume & Reload Application
          </button>
        </div>
      </div>
    );
  }

  // Case 2: Scraper is currently active - The User's Single Screen Pop!
  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/90 backdrop-blur-xl p-4 select-none">
      <div className="relative bg-[#0F172A] border border-amber-500/30 rounded-3xl p-7 md:p-9 max-w-xl w-full shadow-2xl text-slate-100 overflow-hidden space-y-6">
        
        {/* Decorative ambient glowing top pill */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-1.5 bg-gradient-to-r from-amber-500 via-orange-500 to-amber-500 rounded-full shadow-[0_0_20px_rgba(245,158,11,0.6)]" />

        {/* Top Header Badge */}
        <div className="flex items-center justify-between">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-400 text-xs font-semibold tracking-wide uppercase">
            <Radio className="w-3.5 h-3.5 animate-pulse text-amber-400" />
            <span>RAM Conservation Mode</span>
          </div>

          <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-800/80 px-3 py-1 rounded-full border border-slate-700/60 font-mono">
            <Clock className="w-3.5 h-3.5 text-amber-400" />
            <span>Active: {formatTime(elapsedSeconds)}</span>
          </div>
        </div>

        {/* Hero Visual Icon */}
        <div className="flex items-center gap-4">
          <div className="relative flex-shrink-0">
            <div className="w-16 h-16 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 shadow-lg shadow-amber-500/10">
              <Cpu className="w-8 h-8 animate-pulse" />
            </div>
            <span className="absolute -top-1 -right-1 flex h-3.5 w-3.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-amber-500"></span>
            </span>
          </div>

          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              The Scraper is Currently Active
            </h1>
            <p className="text-xs text-amber-400 font-medium tracking-wide mt-0.5">
              VANTIS AUTOMATED DATA PIPELINE IN PROGRESS • RAM PROTECTED
            </p>
          </div>
        </div>

        {/* Core Notice Box requested by user */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 space-y-3">
          <div className="flex items-start gap-3">
            <ShieldAlert className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-slate-300 leading-relaxed">
              <strong className="text-white font-semibold block text-base mb-1">
                The scraper is currently active. Come back later after 1 hour as we don't have enough RAM to load all the data presently.
              </strong>
              <span className="text-slate-400 text-xs">
                {customMsg || "All in-memory catalog data has been cleared to prevent memory overload during scraping. Access to all pages will be unlocked automatically as soon as the pipeline completes."}
              </span>
            </div>
          </div>

          <div className="pt-2 border-t border-slate-800/80 grid grid-cols-2 gap-3 text-xs">
            <div className="bg-slate-800/50 rounded-xl p-2.5 border border-slate-700/40">
              <div className="text-slate-400 flex items-center gap-1.5 font-medium mb-1">
                <Database className="w-3.5 h-3.5 text-emerald-400" />
                RAM Protection
              </div>
              <div className="text-emerald-400 font-semibold">
                Purged &amp; Locked
              </div>
            </div>

            <div className="bg-slate-800/50 rounded-xl p-2.5 border border-slate-700/40">
              <div className="text-slate-400 flex items-center gap-1.5 font-medium mb-1">
                <Clock className="w-3.5 h-3.5 text-amber-400" />
                Estimated Duration
              </div>
              <div className="text-slate-200 font-semibold">
                Up to ~1 Hour
              </div>
            </div>
          </div>
        </div>

        {/* Platform Queues List */}
        <div className="bg-slate-900/40 rounded-xl p-3 border border-slate-800/60 text-xs space-y-2">
          <div className="text-slate-400 flex items-center justify-between font-medium">
            <span>Platforms in sequential scrape queue:</span>
            <span className="text-amber-400/90">Playwright &amp; GraphQL Engine</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Columbia India", "Adventuras", "Tata CLiQ", "Tata CLiQ Luxury", "Amazon"].map((plat) => (
              <span
                key={plat}
                className="px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700/70 text-slate-300 text-[11px] font-medium"
              >
                {plat}
              </span>
            ))}
          </div>
        </div>

        {/* Action Controls */}
        <div className="pt-2 flex items-center gap-3">
          <button
            onClick={() => checkStatus()}
            disabled={isChecking}
            className="flex-1 py-3 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700/80 text-slate-200 text-sm font-semibold transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${isChecking ? "animate-spin text-amber-400" : ""}`} />
            <span>{isChecking ? "Checking Status..." : "Check Status"}</span>
          </button>

          {/* Admin Emergency Halt option */}
          <button
            onClick={handleStopScraper}
            disabled={isStopping}
            className="py-3 px-4 rounded-xl bg-red-950/40 hover:bg-red-900/60 border border-red-800/50 text-red-300 hover:text-red-200 text-sm font-medium transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
            title="Emergency halt for scraper pipeline"
          >
            <Square className="w-3.5 h-3.5 fill-red-400 text-red-400" />
            <span>{isStopping ? "Halting..." : "Halt Scraper"}</span>
          </button>
        </div>

        <div className="text-center">
          <p className="text-[11px] text-slate-500">
            Auto-checking every 12 seconds • Catalog reload is locked until pipeline finishes.
          </p>
        </div>

      </div>
    </div>
  );
};

export default ScrapingLockModal;
