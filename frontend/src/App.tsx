import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import HomePage from "./pages/HomePage";
import ProductDetailsPage from "./pages/ProductDetailsPage";
import CataloguePage from "./pages/CataloguePage";
import AnalysisPage from "./pages/AnalysisPage";
import SystemStatusPage from "./pages/SystemStatusPage";
import ProfilePage from "./pages/ProfilePage";
import ProtectedRoute from "./components/layout/ProtectedRoute";
import authService from "./services/authService";

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public Login Route */}
        <Route
          path="/login"
          element={<LoginPage />}
        />

        {/* Authenticated Routes with Persistent Header & Fixed Bottom Dock */}
        <Route
          path="/home"
          element={
            <ProtectedRoute>
              <HomePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/products/:familyId"
          element={
            <ProtectedRoute>
              <ProductDetailsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/catalogue"
          element={
            <ProtectedRoute>
              <CataloguePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/analysis"
          element={
            <ProtectedRoute>
              <AnalysisPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/system-status"
          element={
            <ProtectedRoute>
              <SystemStatusPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/profile"
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          }
        />

        {/* Root and Catch-all Redirection: Root / always sends to login */}
        <Route
          path="/"
          element={<Navigate to="/login" replace />}
        />
        <Route
          path="*"
          element={<Navigate to="/login" replace />}
        />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
