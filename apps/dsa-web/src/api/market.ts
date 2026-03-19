import apiClient from './index';
import { toCamelCase } from './utils';
import type { MarketOverviewResponse, SectorConstituentResponse } from '../types/market';

export interface MarketOverviewOptions {
  includeSummary?: boolean;
  includeWatchlist?: boolean;
}

export const marketApi = {
  async getOverview(forceRefresh = false, options: MarketOverviewOptions = {}): Promise<MarketOverviewResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/market/overview', {
      params: {
        force_refresh: forceRefresh || undefined,
        include_summary: options.includeSummary === false ? false : undefined,
        include_watchlist: options.includeWatchlist === false ? false : undefined,
      },
    });
    return toCamelCase<MarketOverviewResponse>(response.data);
  },

  async getSectorConstituents(
    sectorName: string,
    forceRefresh = false,
    limit = 10,
  ): Promise<SectorConstituentResponse> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/market/sectors/${encodeURIComponent(sectorName)}/constituents`,
      {
        params: {
          force_refresh: forceRefresh || undefined,
          limit,
        },
      },
    );
    return toCamelCase<SectorConstituentResponse>(response.data);
  },
};
