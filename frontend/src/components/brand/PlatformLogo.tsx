import React from "react";

interface PlatformLogoProps {
  platform: string;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
  className?: string;
}

export const PlatformLogo: React.FC<PlatformLogoProps> = ({
  platform,
  size = "md",
  showLabel = false,
  className = "",
}) => {
  const norm = (platform || "").toLowerCase();

  const dimensions = {
    sm: "w-5 h-5 text-xs",
    md: "w-6 h-6 text-sm",
    lg: "w-8 h-8 text-base",
  };

  const renderIcon = () => {
    switch (norm) {
      case "amazon":
        return (
          <div className={`${dimensions[size]} bg-white border border-slate-200 rounded flex items-center justify-center p-0.5 shadow-xs`}>
            <span className="font-bold text-slate-900 tracking-tighter lowercase leading-none text-[0.85em]">a</span>
            <span className="text-amber-500 font-extrabold text-[0.65em] -ml-0.5">⌣</span>
          </div>
        );

      case "tata":
      case "tatacliq":
        return (
          <div className={`${dimensions[size]} bg-[#b81f33] rounded flex items-center justify-center text-white font-bold shadow-xs`}>
            <span className="text-[0.75em]">Q</span>
          </div>
        );

      case "tata_lux":
      case "tatacliq_luxury":
        return (
          <div className={`${dimensions[size]} bg-[#8b5a2b] rounded flex items-center justify-center text-white font-serif font-black shadow-xs`}>
            <span className="text-[0.75em]">T</span>
          </div>
        );

      case "columbia":
      case "columbiasportswear":
        return (
          <div className={`${dimensions[size]} bg-[#079FE0] rounded flex items-center justify-center text-white p-0.5 shadow-xs`}>
            <svg viewBox="0 0 100 100" className="w-full h-full fill-white">
              <rect x="22" y="22" width="24" height="24" rx="2" transform="rotate(45 34 34)" />
              <rect x="54" y="22" width="24" height="24" rx="2" transform="rotate(45 66 34)" />
              <rect x="22" y="54" width="24" height="24" rx="2" transform="rotate(45 34 66)" />
              <rect x="54" y="54" width="24" height="24" rx="2" transform="rotate(45 66 66)" />
            </svg>
          </div>
        );

      case "adv":
      case "adventuras":
      case "advaatars":
        return (
          <div className={`${dimensions[size]} bg-black rounded-full flex items-center justify-center text-white font-bold shadow-xs`}>
            <span className="text-[0.7em]">A</span>
          </div>
        );

      case "myntra":
        return (
          <div className={`${dimensions[size]} bg-gradient-to-tr from-rose-500 via-amber-400 to-pink-500 rounded flex items-center justify-center text-white font-black shadow-xs`}>
            <span className="text-[0.75em]">M</span>
          </div>
        );

      case "ajio":
        return (
          <div className={`${dimensions[size]} bg-slate-900 rounded-full flex items-center justify-center text-white font-bold shadow-xs`}>
            <span className="text-[0.7em]">A</span>
          </div>
        );

      default:
        return (
          <div className={`${dimensions[size]} bg-slate-200 rounded flex items-center justify-center text-slate-700 font-semibold shadow-xs`}>
            <span>{platform.slice(0, 1).toUpperCase()}</span>
          </div>
        );
    }
  };

  const getLabel = () => {
    switch (norm) {
      case "amazon":
        return "Amazon";
      case "tata":
        return "Tata CLiQ";
      case "tata_lux":
        return "Tata CLiQ Luxury";
      case "columbia":
        return "Columbia";
      case "adv":
        return "Advaatars";
      case "myntra":
        return "Myntra";
      case "ajio":
        return "AJIO";
      default:
        return platform;
    }
  };

  return (
    <div className={`inline-flex items-center gap-2 ${className}`}>
      {renderIcon()}
      {showLabel && <span className="font-medium text-slate-800 text-sm">{getLabel()}</span>}
    </div>
  );
};

export default PlatformLogo;
