import React from "react";
import Header from "./Header";
import BottomDock from "./BottomDock";

interface AppLayoutProps {
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  return (
    <div className="h-screen w-screen overflow-hidden bg-[#F8FAFC] flex flex-col antialiased">
      <Header />
      <main className="flex-1 overflow-y-auto pb-28">
        {children}
      </main>
      <BottomDock />
    </div>
  );
};

export default AppLayout;
