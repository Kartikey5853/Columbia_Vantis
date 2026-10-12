import React from "react";
import { Link } from "react-router-dom";

interface VantisLogoProps {
  className?: string;
  variant?: "header" | "big";
  asLink?: boolean;
}

export const VantisLogo: React.FC<VantisLogoProps> = ({
  className = "",
  variant = "header",
  asLink = true,
}) => {
  const content = (
    <div className={`inline-flex items-center select-none ${className}`}>
      {variant === "big" ? (
        <img
          src="/vantis_big_logo.png"
          alt="Columbia VANTIS"
          className="h-20 sm:h-24 w-auto object-contain max-w-full drop-shadow-xs"
        />
      ) : (
        <img
          src="/vantis_header_logo.png"
          alt="Columbia VANTIS"
          className="h-9 sm:h-10 w-auto object-contain max-w-full drop-shadow-2xs"
        />
      )}
    </div>
  );

  if (!asLink) {
    return content;
  }

  return (
    <Link to="/home" className="inline-block hover:opacity-95 transition-opacity">
      {content}
    </Link>
  );
};

export default VantisLogo;
