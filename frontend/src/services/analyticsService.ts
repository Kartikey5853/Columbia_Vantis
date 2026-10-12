import apiClient from "./apiClient";
import { AnalyticsSummary, AnalyticsProductRow, ProductPriceHistoryResponse } from "../types";

export interface AnalyticsFilterParams {
  page?: number;
  page_size?: number;
  search?: string;
  category?: string;
  gender?: string;
  platform?: string;
  sort_by?: string;
}

export interface AnalyticsProductsResponse {
  total_records: number;
  page: number;
  page_size: number;
  total_pages: number;
  products: AnalyticsProductRow[];
}

export const analyticsService = {
  async getSummary(): Promise<AnalyticsSummary> {
    const response = await apiClient.get<AnalyticsSummary>("/api/analytics/summary");
    return response.data;
  },

  async getProducts(params: AnalyticsFilterParams = {}): Promise<AnalyticsProductsResponse> {
    const response = await apiClient.get<AnalyticsProductsResponse>("/api/analytics/products", {
      params,
    });
    return response.data;
  },

  async getPriceHistory(familyId: string, range: string = "6M"): Promise<ProductPriceHistoryResponse> {
    const response = await apiClient.get<ProductPriceHistoryResponse>("/api/analytics/price-history", {
      params: { family_id: familyId, range },
    });
    return response.data;
  },

  async getPlatformComparison(): Promise<any> {
    const response = await apiClient.get("/api/analytics/platform-comparison");
    return response.data;
  },

  async getCategories(): Promise<any> {
    const response = await apiClient.get("/api/analytics/categories");
    return response.data;
  },
};

export default analyticsService;
