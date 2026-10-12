import React, { useState } from "react";

interface PlatformLogoProps {
  platform: string;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
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
  const [hasError, setHasError] = useState(false);

  const dimensions = {
    xs: "w-4 h-4",
    sm: "w-6 h-6",
    md: "w-7 h-7",
    lg: "w-9 h-9",
    xl: "w-11 h-11",
  };

  const getLogoSrc = (): string | null => {
    switch (norm) {
      case "amazon":
        return "/logos/amazon.svg";
      case "columbia":
      case "columbiasportswear":
        return "/logos/columbia.svg";
      case "tata":
      case "tatacliq":
        return "/logos/tata.svg";
      case "tata_lux":
      case "tatacliq_luxury":
        return "/logos/tata_lux.svg";
      case "ajio":
        return "/logos/ajio.svg";
      case "myntra":
        return "/logos/myntra.svg";
      case "adv":
      case "adventuras":
      case "advaatars":
        return "/logos/adv.svg";
      default:
        return null;
    }
  };

  const getLabel = () => {
    switch (norm) {
      case "amazon":
        return "Amazon";
      case "tata":
      case "tatacliq":
        return "Tata CLiQ";
      case "tata_lux":
      case "tatacliq_luxury":
        return "Tata CLiQ Luxury";
      case "columbia":
      case "columbiasportswear":
        return "Columbia";
      case "adv":
      case "adventuras":
      case "advaatars":
        return "Advaatars";
      case "myntra":
        return "Myntra";
      case "ajio":
        return "AJIO";
      default:
        return platform ? platform.charAt(0).toUpperCase() + platform.slice(1) : "";
    }
  };

  const logoSrc = getLogoSrc();

  const renderIcon = () => {
    if (logoSrc && !hasError) {
      return (
        <div
          className={`${dimensions[size]} bg-white border border-slate-200/80 rounded-lg p-0.5 flex items-center justify-center shrink-0 shadow-2xs overflow-hidden`}
        >
          <img
            src={logoSrc}
            alt={getLabel()}
            onError={() => setHasError(true)}
            className="w-full h-full object-contain"
            loading="lazy"
          />
        </div>
      );
    }

    // Fallback if SVG missing
    return (
      <div
        className={`${dimensions[size]} bg-slate-900 rounded-lg text-white font-bold text-xs flex items-center justify-center shrink-0 shadow-2xs`}
      >
        <span>{platform ? platform.slice(0, 1).toUpperCase() : "P"}</span>
      </div>
    );
  };

  return (
    <div className={`inline-flex items-center gap-2 ${className}`}>
      {renderIcon()}
      {showLabel && (
        <span className="font-bold text-slate-800 text-xs sm:text-sm whitespace-nowrap">
          {getLabel()}
        </span>
      )}
    </div>
  );
};

export default PlatformLogo;
