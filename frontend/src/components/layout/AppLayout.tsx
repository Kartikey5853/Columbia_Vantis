import React from "react";
import { useLocation } from "react-router-dom";
import Header from "./Header";
import BottomDock from "./BottomDock";

interface AppLayoutProps {
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  const location = useLocation();
  const isAnalysis = location.pathname === "/analysis";

  return (
    <div className="h-screen w-screen overflow-hidden bg-[#F8FAFC] flex flex-col antialiased">
      <Header />
      <main className={`flex-1 ${isAnalysis ? "overflow-hidden flex flex-col pb-20" : "overflow-y-auto pb-28"}`}>
        {children}
      </main>
      <BottomDock />
    </div>
  );
};

export default AppLayout;
