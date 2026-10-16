import apiClient from "./apiClient";
import { PaginatedProductsResponse, AnalyticsProductRow, SystemStatusSummary } from "../types";

export interface SystemBundleResponse {
  status: string;
  catalog: PaginatedProductsResponse;
  analytics: {
    total_records: number;
    page: number;
    page_size: number;
    total_pages: number;
    products: AnalyticsProductRow[];
  };
  system: {
    summary: SystemStatusSummary;
    scrapers: any[];
    servers: any[];
  };
}

let cachedBundle: SystemBundleResponse | null = null;
let inflightPromise: Promise<SystemBundleResponse> | null = null;

export const bundleService = {
  async getBundle(forceRefresh: boolean = false): Promise<SystemBundleResponse> {
    if (!forceRefresh && cachedBundle) {
      return cachedBundle;
    }

    if (!forceRefresh && inflightPromise) {
      return inflightPromise;
    }

    inflightPromise = apiClient
      .get<SystemBundleResponse>("/api/system/bundle", { timeout: 30000 })
      .then((res) => {
        cachedBundle = res.data;
        inflightPromise = null;
        return res.data;
      })
      .catch((err) => {
        inflightPromise = null;
        throw err;
      });

    return inflightPromise;
  },

  getCachedBundle(): SystemBundleResponse | null {
    return cachedBundle;
  },

  clearCache(): void {
    cachedBundle = null;
    inflightPromise = null;
  },
};

export default bundleService;
