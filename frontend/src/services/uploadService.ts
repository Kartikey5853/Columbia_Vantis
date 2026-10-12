import apiClient from "./apiClient";
import { MasterDataStatus } from "../types";

export const uploadService = {
  async getMasterDataStatus(): Promise<MasterDataStatus> {
    const response = await apiClient.get<MasterDataStatus>("/api/master-data/status");
    return response.data;
  },

  async uploadMasterExcel(file: File, onProgress?: (pct: number) => void): Promise<any> {
    const formData = new FormData();
    formData.append("file", file);

    const response = await apiClient.post("/api/master-data/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total && onProgress) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    });

    return response.data;
  },

  async getJobStatus(jobId: string): Promise<any> {
    const response = await apiClient.get(`/api/master-data/jobs/${jobId}`);
    return response.data;
  },
};

export default uploadService;
