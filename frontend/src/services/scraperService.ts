import apiClient from "./apiClient";
import { SystemStatusSummary, ScraperPlatformStatus, ServerStatus, RecentRun } from "../types";

export const scraperService = {
  async getSystemSummary(): Promise<SystemStatusSummary> {
    const response = await apiClient.get<SystemStatusSummary>("/api/system/summary");
    return response.data;
  },

  async getScrapers(): Promise<ScraperPlatformStatus[]> {
    const response = await apiClient.get<{ scrapers: ScraperPlatformStatus[] }>("/api/system/scrapers");
    return response.data.scrapers;
  },

  async getServers(): Promise<ServerStatus[]> {
    const response = await apiClient.get<{ servers: ServerStatus[] }>("/api/system/servers");
    return response.data.servers;
  },

  async getRecentRuns(): Promise<RecentRun[]> {
    const response = await apiClient.get<{ runs: RecentRun[] }>("/api/system/recent-runs");
    return response.data.runs;
  },

  async triggerScrape(scrapers: string = "columbia,adv,tata,tata_lux,amazon", force: boolean = false): Promise<any> {
    const response = await apiClient.post("/scrape", null, {
      params: { scrapers, force },
    });
    return response.data;
  },

  async stopScraper(reason: string = "Stopped via VANTIS Admin Dashboard"): Promise<any> {
    const response = await apiClient.post("/scrape/stop", null, {
      params: { reason },
    });
    return response.data;
  },

  async resetScraper(scraper: string = "all"): Promise<any> {
    const response = await apiClient.post("/scrape/reset", null, {
      params: { scrapers: scraper },
    });
    return response.data;
  },
};

export default scraperService;
