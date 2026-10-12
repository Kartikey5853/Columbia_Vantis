import React, { useState, useEffect } from "react";
import VantisLogo from "../brand/VantisLogo";

interface SplashScreenProps {
  onComplete: () => void;
  durationMs?: number;
}

export const SplashScreen: React.FC<SplashScreenProps> = ({
  onComplete,
  durationMs = 2000,
}) => {
  const [progress, setProgress] = useState(15);
  const [statusText, setStatusText] = useState("Initializing VANTIS intelligence engine...");

  useEffect(() => {
    const timer1 = setTimeout(() => {
      setProgress(55);
      setStatusText("Connecting to Supabase persistence & price history...");
    }, durationMs * 0.3);

    const timer2 = setTimeout(() => {
      setProgress(85);
      setStatusText("Indexing 7-platform product catalogue...");
    }, durationMs * 0.65);

    const timer3 = setTimeout(() => {
      setProgress(100);
      setStatusText("Ready");
    }, durationMs * 0.9);

    const timer4 = setTimeout(() => {
      onComplete();
    }, durationMs);

    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
      clearTimeout(timer4);
    };
  }, [durationMs, onComplete]);

  return (
    <div className="fixed inset-0 z-50 bg-white flex flex-col items-center justify-center p-6 selection:bg-sky-100 animate-in fade-in duration-300">
      <div className="flex flex-col items-center max-w-sm w-full space-y-6">
        {/* Animated Big Logo */}
        <div className="animate-pulse duration-1000">
          <VantisLogo variant="big" asLink={false} />
        </div>

        {/* Shimmering Progress Bar */}
        <div className="w-full max-w-xs space-y-2">
          <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
            <div
              className="bg-gradient-to-r from-sky-400 to-[#079FE0] h-full rounded-full transition-all duration-500 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="text-center">
            <p className="text-[11px] font-medium text-slate-400 tracking-wide transition-all">
              {statusText}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SplashScreen;
