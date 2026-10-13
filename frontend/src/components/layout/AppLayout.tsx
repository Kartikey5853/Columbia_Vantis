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
    <div
      className="h-screen w-screen overflow-hidden flex flex-col antialiased bg-cover bg-center bg-no-repeat bg-fixed relative"
      style={{ backgroundImage: "url('/inside.png')" }}
    >
      <div className="absolute inset-0 bg-[#F8FAFC]/25 pointer-events-none" />
      <div className="relative z-10 flex flex-col h-full w-full overflow-hidden">
        <Header />
        <main className={`flex-1 ${isAnalysis ? "overflow-hidden flex flex-col pb-20" : "overflow-y-auto pb-28"}`}>
          {children}
        </main>
        <BottomDock />
      </div>
    </div>
  );
};

export default AppLayout;
