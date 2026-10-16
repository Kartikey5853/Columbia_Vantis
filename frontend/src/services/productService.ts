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

  async exportCatalogExcel(params: ProductFilterParams = {}): Promise<void> {
    const response = await apiClient.get("/api/products/export-excel", {
      params: {
        search: params.search,
        category: params.category,
        gender: params.gender,
        platform: params.platform,
        min_price: params.min_price,
        max_price: params.max_price,
        limit: 1000,
      },
      responseType: "blob",
    });

    const blob = new Blob([response.data], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = params.search ? `Columbia_Search_${params.search}.xlsx` : "Columbia_Omnichannel_Catalogue.xlsx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },

  async exportSelectedExcel(familyIds: string[]): Promise<void> {
    const response = await apiClient.post(
      "/api/products/export-excel",
      { family_ids: familyIds },
      { responseType: "blob" }
    );

    const blob = new Blob([response.data], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Columbia_Selected_${familyIds.length}_Products.xlsx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },
};

export default productService;
