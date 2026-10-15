import React, { useState, useEffect, useRef } from "react";
import VantisLogo from "../brand/VantisLogo";
import apiClient from "../../services/apiClient";

interface SplashScreenProps {
  onComplete?: () => void;
  maxWaitSeconds?: number;
}

export const SplashScreen: React.FC<SplashScreenProps> = ({
  onComplete,
  maxWaitSeconds = 90,
}) => {
  const [secondsElapsed, setSecondsElapsed] = useState(0);
  const [isServerReady, setIsServerReady] = useState(false);
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

    // Check server health immediately and repeatedly
    const checkServer = async () => {
      try {
        const res = await apiClient.get("/api/health", { timeout: 2500 });
        if (res.status === 200) {
          setIsServerReady(true);
          finish();
          return;
        }
      } catch {
        try {
          const res = await apiClient.get("/health", { timeout: 2500 });
          if (res.status === 200) {
            setIsServerReady(true);
            finish();
            return;
          }
        } catch {
          // Server might still be waking up on Render free tier
        }
      }
    };

    checkServer();
    pollInterval = setInterval(checkServer, 1500);

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
            Connecting to server... It might take around a minute to turn on the server.
          </p>
          <p className="text-xs sm:text-sm font-semibold text-slate-400">
            {isServerReady
              ? "Server responded. Entering workspace..."
              : `Checking connection (${secondsElapsed}s / ${maxWaitSeconds}s)...`}
          </p>
        </div>

        {/* Clean Progress Line */}
        <div className="w-full max-w-xs bg-slate-100 rounded-full h-2 overflow-hidden shadow-inner">
          <div
            className="bg-gradient-to-r from-sky-400 to-[#079FE0] h-full rounded-full transition-all duration-700 ease-out"
            style={{ width: `${Math.max(8, progressPercent)}%` }}
          />
        </div>
      </div>
    </div>
  );
};

export default SplashScreen;
