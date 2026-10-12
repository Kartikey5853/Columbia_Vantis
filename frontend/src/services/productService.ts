import apiClient from "./apiClient";
import { ProductFamily, ProductFamilySummary, PaginatedProductsResponse } from "../types";

export interface ProductFilterParams {
  page?: number;
  page_size?: number;
  search?: string;
  category?: string;
  gender?: string;
  platform?: string;
  min_price?: number;
  max_price?: number;
  sort_by?: string;
}

export const productService = {
  async getProducts(params: ProductFilterParams = {}): Promise<PaginatedProductsResponse> {
    const response = await apiClient.get<PaginatedProductsResponse>("/api/products", {
      params,
    });
    return response.data;
  },

  async searchProducts(query: string, limit: number = 24): Promise<ProductFamilySummary[]> {
    const response = await apiClient.get<ProductFamilySummary[]>("/api/products/search", {
      params: { q: query, limit },
    });
    return response.data;
  },

  async bulkSearch(identifiers: string[]): Promise<ProductFamilySummary[]> {
    const response = await apiClient.post<ProductFamilySummary[]>("/api/products/bulk-search", {
      identifiers,
    });
    return response.data;
  },

  async getProductDetails(familyId: string): Promise<ProductFamily> {
    const response = await apiClient.get<ProductFamily>(`/api/products/${encodeURIComponent(familyId)}`);
    return response.data;
  },
};

export default productService;
