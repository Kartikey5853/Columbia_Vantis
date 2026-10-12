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
          alt="Columbia Sportswear"
          className="h-24 sm:h-32 md:h-40 w-auto object-contain max-w-full"
        />
      ) : (
        <img
          src="/vantis_header_logo.png"
          alt="Columbia Sportswear"
          className="h-8 sm:h-9 max-h-9 w-auto object-contain max-w-full"
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
