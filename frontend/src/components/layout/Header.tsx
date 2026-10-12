import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { FileSpreadsheet, Plus, LogOut, User as UserIcon } from "lucide-react";
import VantisLogo from "../brand/VantisLogo";
import MasterExcelModal from "./MasterExcelModal";
import authService from "../../services/authService";
import { User } from "../../types";

interface HeaderProps {
  user?: User | null;
  onRefresh?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ user: propUser, onRefresh }) => {
  const navigate = useNavigate();
  const [isExcelModalOpen, setIsExcelModalOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);

  const user = propUser || authService.getSavedUser();

  const handleLogout = async () => {
    await authService.logout();
    navigate("/login");
  };

  return (
    <>
      <header className="sticky top-0 z-40 w-full bg-white border-b border-slate-200/80 px-4 sm:px-8 py-3">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
          {/* Left: Brand Logo */}
          <div className="flex items-center gap-3">
            <VantisLogo variant="header" />
          </div>

          {/* Right: Master Excel Control & User Avatar */}
          <div className="flex items-center gap-3 sm:gap-4">
            {/* Master Excel Button */}
            <button
              onClick={() => setIsExcelModalOpen(true)}
              className="inline-flex items-center gap-2 px-3 sm:px-4 py-1.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs sm:text-sm font-medium transition-all shadow-2xs group"
            >
              <div className="w-5 h-5 rounded bg-emerald-100 text-emerald-700 flex items-center justify-center shrink-0">
                <FileSpreadsheet className="w-3.5 h-3.5" />
              </div>
              <span className="hidden xs:inline font-semibold">Master Excel</span>
              <div className="w-4 h-4 rounded-full bg-sky-500 text-white flex items-center justify-center group-hover:bg-sky-600 transition-colors">
                <Plus className="w-3 h-3 stroke-[3]" />
              </div>
            </button>

            {/* User Avatar with Dropdown */}
            <div className="relative">
              <button
                onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
                className="w-9 h-9 rounded-full ring-2 ring-slate-100 hover:ring-sky-400 transition-all overflow-hidden flex items-center justify-center bg-sky-100 text-sky-800 font-bold text-xs"
              >
                {user?.avatar_url ? (
                  <img
                    src={user.avatar_url}
                    alt={user.display_name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <span>{user?.display_name?.slice(0, 2).toUpperCase() || "CV"}</span>
                )}
              </button>

              {/* Dropdown Menu */}
              {isUserMenuOpen && (
                <>
                  <div
                    className="fixed inset-0 z-30"
                    onClick={() => setIsUserMenuOpen(false)}
                  />
                  <div className="absolute right-0 mt-2 w-56 bg-white rounded-xl shadow-xl border border-slate-200/80 py-1.5 z-40 animate-in fade-in zoom-in-95 duration-100">
                    <div className="px-4 py-2 border-b border-slate-100">
                      <div className="font-semibold text-slate-800 text-sm truncate">
                        {user?.display_name || "Columbia User"}
                      </div>
                      <div className="text-xs text-slate-400 truncate">
                        {user?.email || "employee@columbia.com"}
                      </div>
                    </div>
                    <Link
                      to="/profile"
                      onClick={() => setIsUserMenuOpen(false)}
                      className="flex items-center gap-2.5 px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors"
                    >
                      <UserIcon className="w-4 h-4 text-slate-400" />
                      <span>Account Profile</span>
                    </Link>
                    <button
                      onClick={handleLogout}
                      className="w-full flex items-center gap-2.5 px-4 py-2 text-xs font-medium text-rose-600 hover:bg-rose-50 transition-colors text-left"
                    >
                      <LogOut className="w-4 h-4 text-rose-500" />
                      <span>Sign Out</span>
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Master Excel Upload Modal */}
      <MasterExcelModal
        isOpen={isExcelModalOpen}
        onClose={() => setIsExcelModalOpen(false)}
        onSuccess={onRefresh}
      />
    </>
  );
};

export default Header;
