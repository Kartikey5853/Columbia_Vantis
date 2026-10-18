import React, { useState, useEffect, useRef } from "react";
import VantisLogo from "../brand/VantisLogo";
import apiClient from "../../services/apiClient";
import bundleService from "../../services/bundleService";
import authService from "../../services/authService";

interface SplashScreenProps {
  onComplete?: () => void;
  maxWaitSeconds?: number;
  message?: string;
  subMessage?: string;
}

export const SplashScreen: React.FC<SplashScreenProps> = ({
  onComplete,
  maxWaitSeconds = 90,
  message,
  subMessage,
}) => {
  const [secondsElapsed, setSecondsElapsed] = useState(0);
  const [isServerReady, setIsServerReady] = useState(false);
  const [statusText, setStatusText] = useState<string>(
    subMessage || "Connecting to database & loading workspace..."
  );
  const completedRef = useRef(false);

  const finish = () => {
    if (!completedRef.current) {
      completedRef.current = true;
      if (onComplete) {
        onComplete();
      }
    }
  };

  useEffect(() => {
    document.body.classList.add("splash-active");
    let timer: any = null;
    let pollInterval: any = null;
    let isChecking = false;

    // Check server health and ensure all bundle data is loaded
    const checkServerAndData = async () => {
      if (isChecking || completedRef.current) return;
      isChecking = true;

      try {
        let ok = false;
        try {
          const res = await apiClient.get("/api/health", { timeout: 3000 });
          if (res.status === 200) ok = true;
        } catch {
          const res = await apiClient.get("/health", { timeout: 3000 });
          if (res.status === 200) ok = true;
        }

        if (ok) {
          setIsServerReady(true);
          // If authenticated, also wait until system bundle is completely loaded
          if (authService.isAuthenticated()) {
            setStatusText("Loading catalogue & real-time telemetry...");
            try {
              await bundleService.getBundle();
            } catch {
              // Proceed even if bundle fails
            }
          }
          setStatusText("All data loaded! Launching dashboard...");
          setTimeout(() => {
            finish();
          }, 400);
          return;
        }
      } catch {
        // Server still spinning up
      } finally {
        isChecking = false;
      }
    };

    checkServerAndData();
    pollInterval = setInterval(checkServerAndData, 1500);

    // Track elapsed time up to maxWaitSeconds
    timer = setInterval(() => {
      setSecondsElapsed((prev) => {
        const next = prev + 1;
        if (next >= maxWaitSeconds) {
          finish();
        }
        return next;
      });
    }, 1000);

    return () => {
      document.body.classList.remove("splash-active");
      if (timer) clearInterval(timer);
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [maxWaitSeconds]);

  const progressPercent = Math.min(100, Math.round((secondsElapsed / maxWaitSeconds) * 100));

  return (
    <div className="fixed inset-0 z-50 bg-white flex flex-col items-center justify-center p-8 select-none">
      <div className="flex flex-col items-center max-w-lg w-full space-y-10 animate-in fade-in duration-300 text-center">
        {/* 2X Enlarged Columbia Logo */}
        <div className="transform scale-110 sm:scale-125 transition-transform duration-700">
          <VantisLogo variant="big" asLink={false} />
        </div>

        {/* 2X Enlarged Animated Pulsing Spinner */}
        <div className="relative flex items-center justify-center">
          <div className="w-16 h-16 rounded-full border-4 border-slate-100 border-t-[#079FE0] animate-spin" />
          <div className="absolute w-20 h-20 rounded-full border border-sky-200/50 animate-ping duration-1000 opacity-30" />
        </div>

        {/* Status Text as explicitly requested by user */}
        <div className="space-y-3 px-4 max-w-md">
          <p className="text-base sm:text-lg font-bold text-slate-800 leading-snug">
            {message || "Loading Columbia Platform Intelligence"}
          </p>
          <p className="text-xs sm:text-sm font-semibold text-slate-400">
            {subMessage ||
              (isServerReady
                ? statusText
                : `Connecting to server (${secondsElapsed}s / ${maxWaitSeconds}s)...`)}
          </p>
        </div>

        {/* Clean Progress Line */}
        <div className="w-full max-w-xs bg-slate-100 rounded-full h-2 overflow-hidden shadow-inner">
          <div
            className="bg-gradient-to-r from-sky-400 to-[#079FE0] h-full rounded-full transition-all duration-700 ease-out"
            style={{ width: `${Math.max(12, isServerReady ? 92 : progressPercent)}%` }}
          />
        </div>
      </div>
    </div>
  );
};

export default SplashScreen;
