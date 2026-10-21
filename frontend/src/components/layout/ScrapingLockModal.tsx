import React, { useEffect, useState, useCallback, useRef } from "react";
import { Cpu, ShieldAlert, RefreshCw, Clock, Database, CheckCircle2, Square, Radio, AlertOctagon } from "lucide-react";
import scraperService from "../../services/scraperService";

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
      // In case backend is temporarily unreachable, maintain current state
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
    const confirmStop = window.confirm("Are you sure you want to terminate the active scraping pipeline?");
    if (!confirmStop) return;

    try {
      setIsStopping(true);
      await scraperService.stopScraper("Terminated by user via Scraping Lockdown Screen");
      await checkStatus();
    } catch (err: any) {
      alert("Failed to terminate scraper: " + (err?.message || "Unknown error"));
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
      <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-slate-900/35 backdrop-blur-md p-4 animate-in fade-in duration-300">
        <div className="bg-white/95 backdrop-blur-2xl border border-emerald-500/30 rounded-3xl p-8 max-w-lg w-full shadow-2xl text-center space-y-6">
          <div className="w-16 h-16 bg-emerald-50 text-emerald-600 rounded-full flex items-center justify-center mx-auto shadow-inner border border-emerald-200">
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
            className="w-full py-3.5 px-6 rounded-2xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold shadow-lg shadow-emerald-500/25 transition-all flex items-center justify-center gap-2 cursor-pointer"
          >
            <RefreshCw className="w-4 h-4" />
            Resume &amp; Reload Application
          </button>
        </div>
      </div>
    );
  }

  // Case 2: Scraper is currently active - Clean White Glassmorphic Design requested by user
  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-slate-900/40 backdrop-blur-md p-4 select-none animate-in fade-in duration-200">
      <div className="relative bg-white/95 backdrop-blur-2xl border border-slate-200/90 rounded-3xl p-7 md:p-9 max-w-xl w-full shadow-2xl text-slate-800 overflow-hidden space-y-6">
        
        {/* Decorative subtle ambient top bar */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-1 bg-gradient-to-r from-sky-400 via-blue-500 to-sky-400 rounded-full" />

        {/* Clean Logo Header & Status Badges */}
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-4">
          <div className="flex items-center">
            <img
              src="/vantis_big_logo.png"
              alt="Columbia Sportswear"
              className="h-10 sm:h-12 w-auto object-contain"
            />
          </div>

          <div className="flex items-center gap-2">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700 text-[11px] font-semibold tracking-wide uppercase">
              <span className="w-2 h-2 rounded-full bg-amber-500 inline-block animate-pulse"></span>
              <span>Active</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-slate-500 bg-slate-100 px-3 py-1 rounded-full border border-slate-200 font-mono">
              <Clock className="w-3.5 h-3.5 text-slate-500" />
              <span>{formatTime(elapsedSeconds)}</span>
            </div>
          </div>
        </div>

        {/* Hero Visual & Headline */}
        <div className="text-center space-y-2">
          <div className="w-14 h-14 rounded-2xl bg-sky-50 border border-sky-100 flex items-center justify-center text-sky-600 mx-auto shadow-sm">
            <Cpu className="w-7 h-7 animate-pulse text-sky-600" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            The Scraper is Currently Active
          </h1>
          <p className="text-xs text-slate-500 font-medium">
            RAM CONSERVATION &amp; BACKGROUND DATA PIPELINE IN PROGRESS
          </p>
        </div>

        {/* Core Notice Box requested by user */}
        <div className="bg-slate-50 border border-slate-200/90 rounded-2xl p-5 space-y-3.5">
          <div className="flex items-start gap-3">
            <ShieldAlert className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-slate-700 leading-relaxed">
              <strong className="text-slate-900 font-semibold block text-base mb-1">
                The scraper is currently active. Come back later after 1 hour as we don't have enough RAM to load all the data presently.
              </strong>
              <span className="text-slate-500 text-xs leading-normal block">
                {customMsg || "All in-memory catalog data has been purged to ensure zero memory overages on Render (512 MB). Application access will unlock automatically when scraping completes."}
              </span>
            </div>
          </div>

          <div className="pt-2 border-t border-slate-200 grid grid-cols-2 gap-3 text-xs">
            <div className="bg-white rounded-xl p-2.5 border border-slate-200/80 shadow-2xs">
              <div className="text-slate-500 flex items-center gap-1.5 font-medium mb-1">
                <Database className="w-3.5 h-3.5 text-emerald-600" />
                RAM Protection
              </div>
              <div className="text-emerald-700 font-semibold">
                Purged &amp; Protected
              </div>
            </div>

            <div className="bg-white rounded-xl p-2.5 border border-slate-200/80 shadow-2xs">
              <div className="text-slate-500 flex items-center gap-1.5 font-medium mb-1">
                <Clock className="w-3.5 h-3.5 text-sky-600" />
                Estimated Duration
              </div>
              <div className="text-slate-800 font-semibold">
                Up to ~1 Hour
              </div>
            </div>
          </div>
        </div>

        {/* Sequential Platforms in Scrape Queue */}
        <div className="bg-slate-50/70 rounded-2xl p-3 border border-slate-200 text-xs space-y-2">
          <div className="text-slate-500 flex items-center justify-between font-medium">
            <span>Sequential scrape queue:</span>
            <span className="text-sky-700 font-semibold text-[11px]">Headless Engine</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Columbia India", "Adventuras", "Tata CLiQ", "Tata CLiQ Luxury", "Amazon"].map((plat) => (
              <span
                key={plat}
                className="px-2.5 py-1 rounded-lg bg-white border border-slate-200 text-slate-700 text-[11px] font-medium shadow-2xs"
              >
                {plat}
              </span>
            ))}
          </div>
        </div>

        {/* Action Controls: Terminate Scraper & Check Status */}
        <div className="pt-1 flex items-center gap-3">
          <button
            onClick={() => checkStatus()}
            disabled={isChecking}
            className="flex-1 py-3 px-4 rounded-xl bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-800 text-sm font-semibold transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 shadow-2xs"
          >
            <RefreshCw className={`w-4 h-4 text-slate-600 ${isChecking ? "animate-spin text-sky-600" : ""}`} />
            <span>{isChecking ? "Checking..." : "Check Status"}</span>
          </button>

          {/* User Requested Terminate Button */}
          <button
            onClick={handleStopScraper}
            disabled={isStopping}
            className="py-3 px-5 rounded-xl bg-rose-600 hover:bg-rose-700 text-white shadow-md shadow-rose-600/20 text-sm font-semibold transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
            title="Terminate active scraper pipeline immediately"
          >
            <Square className="w-3.5 h-3.5 fill-white text-white" />
            <span>{isStopping ? "Terminating..." : "Terminate Scraper"}</span>
          </button>
        </div>

        <div className="text-center">
          <p className="text-[11px] text-slate-400">
            Auto-checking every 12 seconds • Catalog reload is locked until pipeline finishes.
          </p>
        </div>

      </div>
    </div>
  );
};

export default ScrapingLockModal;
