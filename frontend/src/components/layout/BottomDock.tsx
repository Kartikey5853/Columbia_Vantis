import React from "react";
import { Link, useLocation } from "react-router-dom";
import { Home, Database, BarChart3, Activity, UserCircle2 } from "lucide-react";

export const BottomDock: React.FC = () => {
  const location = useLocation();
  const currentPath = location.pathname;

  // Don't show dock on login page
  if (currentPath === "/login") {
    return null;
  }

  const navItems = [
    {
      label: "Home",
      to: "/home",
      icon: Home,
      isActive: currentPath === "/home",
    },
    {
      label: "View Data",
      to: "/catalogue",
      icon: Database,
      isActive: currentPath === "/catalogue",
    },
    {
      label: "Data Analysis",
      to: "/analysis",
      icon: BarChart3,
      isActive: currentPath === "/analysis",
    },
    {
      label: "System Status",
      to: "/system-status",
      icon: Activity,
      isActive: currentPath === "/system-status",
    },
    {
      label: "Profile",
      to: "/profile",
      icon: UserCircle2,
      isActive: currentPath === "/profile",
    },
  ];

  return (
    <nav
      aria-label="Bottom Navigation Dock"
      className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 pointer-events-auto"
    >
      <div className="flex items-center gap-1 sm:gap-2 px-3 sm:px-4 py-2 bg-white/95 backdrop-blur-xl border border-slate-200/90 rounded-full shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
        {navItems.map((item) => {
          const IconComponent = item.icon;
          const active = item.isActive;

          return (
            <Link
              key={item.to}
              to={item.to}
              className={`relative flex items-center gap-2 px-3.5 sm:px-4 py-2 rounded-full transition-all duration-200 select-none ${
                active
                  ? "bg-[#079FE0] text-white shadow-xs font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 font-medium"
              }`}
            >
              <IconComponent className={`w-4 h-4 sm:w-4.5 sm:h-4.5 ${active ? "text-white stroke-[2.5]" : "text-slate-500"}`} />
              <span className={`text-xs sm:text-sm tracking-tight ${active ? "inline" : "hidden md:inline"}`}>
                {item.label}
              </span>
              {active && (
                <span className="absolute -top-1 right-1 w-2 h-2 rounded-full bg-sky-300 animate-pulse md:hidden" />
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
};

export default BottomDock;
