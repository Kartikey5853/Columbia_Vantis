import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
  const [avatarLoadError, setAvatarLoadError] = useState(false);

  const [currentUser, setCurrentUser] = useState<User | null>(propUser || authService.getSavedUser());

  React.useEffect(() => {
    if (propUser) setCurrentUser(propUser);
  }, [propUser]);

  React.useEffect(() => {
    const handleSync = () => {
      setCurrentUser(authService.getSavedUser());
      setAvatarLoadError(false);
    };
    window.addEventListener("storage", handleSync);
    window.addEventListener("vantis_user_updated", handleSync);
    return () => {
      window.removeEventListener("storage", handleSync);
      window.removeEventListener("vantis_user_updated", handleSync);
    };
  }, []);

  const user = currentUser;

  const handleLogout = async () => {
    await authService.logout();
    navigate("/login");
  };

  return (
    <>
      <header className="sticky top-0 z-40 w-full bg-white border-b border-slate-100 px-4 sm:px-8 py-2">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
          {/* Left: Brand Logo */}
          <div className="flex items-center">
            <VantisLogo variant="header" />
          </div>

          {/* Right: Master Excel Control & User Avatar */}
          <div className="flex items-center gap-3 sm:gap-4">
            {/* Master Excel Button */}
            <button
              onClick={() => setIsExcelModalOpen(true)}
              className="inline-flex items-center gap-2 px-3 sm:px-4 py-1.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs sm:text-sm font-semibold transition-all group"
            >
              <div className="w-5 h-5 rounded bg-emerald-50 text-emerald-700 flex items-center justify-center shrink-0 border border-emerald-100">
                <FileSpreadsheet className="w-3.5 h-3.5" />
              </div>
              <span className="hidden xs:inline font-bold">Master Excel</span>
              <div className="w-4 h-4 rounded-full bg-[#079FE0] text-white flex items-center justify-center group-hover:bg-[#068ec8] transition-colors">
                <Plus className="w-3 h-3 stroke-[3]" />
              </div>
            </button>

            {/* User Avatar with Dropdown */}
            <div className="relative">
              <button
                onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
                className="w-9 h-9 rounded-full border border-slate-200 hover:border-[#079FE0] transition-all overflow-hidden flex items-center justify-center bg-sky-50 text-sky-800 font-extrabold text-xs"
              >
                {user?.avatar_url && !user.avatar_url.includes("unsplash.com") && !avatarLoadError ? (
                  <img
                    src={user.avatar_url}
                    alt={user.username || user.display_name}
                    className="w-full h-full object-cover"
                    onError={() => setAvatarLoadError(true)}
                  />
                ) : (
                  <span>{user?.username?.slice(0, 2).toUpperCase() || "CV"}</span>
                )}
              </button>

              {/* Dropdown Menu */}
              {isUserMenuOpen && (
                <>
                  <div
                    className="fixed inset-0 z-30"
                    onClick={() => setIsUserMenuOpen(false)}
                  />
                  <div className="absolute right-0 mt-2 w-56 bg-white rounded-2xl shadow-xl border border-slate-100 py-2 z-40 animate-in fade-in zoom-in-95 duration-100">
                    <div className="px-4 py-2 border-b border-slate-100">
                      <div className="font-bold text-slate-900 text-sm truncate">
                        {user?.display_name || user?.username || "Columbia User"}
                      </div>
                      <div className="text-xs text-slate-500 font-medium truncate">
                        @{user?.username || "user"}
                      </div>
                    </div>
                    <Link
                      to="/profile"
                      onClick={() => setIsUserMenuOpen(false)}
                      className="flex items-center gap-2.5 px-4 py-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
                    >
                      <UserIcon className="w-4 h-4 text-slate-400" />
                      <span>Account Profile</span>
                    </Link>
                    <button
                      onClick={handleLogout}
                      className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs font-semibold text-rose-600 hover:bg-rose-50 transition-colors text-left"
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
