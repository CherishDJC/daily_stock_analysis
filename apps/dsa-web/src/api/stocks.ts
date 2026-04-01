import apiClient from './index';
import { toCamelCase } from './utils';

export type ExtractFromImageResponse = {
  codes: string[];
  rawText?: string;
};

export interface StockHistoryPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  amount?: number | null;
  changePercent?: number | null;
}

export interface StockHistoryResponse {
  stockCode: string;
  stockName?: string | null;
  period: string;
  data: StockHistoryPoint[];
}

export interface StockMinuteBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  amount?: number | null;
  changePercent?: number | null;
}

export interface StockIntradayTrade {
  timestamp: string;
  price: number;
  volume?: number | null;
  side?: string | null;
}

export interface StockIntradayResponse {
  stockCode: string;
  stockName?: string | null;
  interval: string;
  source?: string | null;
  tradesSource?: string | null;
  updatedAt?: string | null;
  bars: StockMinuteBar[];
  trades: StockIntradayTrade[];
}

export interface StockFundFlowItem {
  date: string;
  close?: number | null;
  changePercent?: number | null;
  mainNetInflow?: number | null;
  mainNetInflowRatio?: number | null;
  superLargeNetInflow?: number | null;
  superLargeNetInflowRatio?: number | null;
  largeNetInflow?: number | null;
  largeNetInflowRatio?: number | null;
  mediumNetInflow?: number | null;
  mediumNetInflowRatio?: number | null;
  smallNetInflow?: number | null;
  smallNetInflowRatio?: number | null;
}

export interface StockFundFlowResponse {
  stockCode: string;
  stockName?: string | null;
  source?: string | null;
  updatedAt?: string | null;
  data: StockFundFlowItem[];
}

export interface StockMetaResponse {
  stockCode: string;
  stockName?: string | null;
  source?: string | null;
  updatedAt?: string | null;
  industry?: string | null;
  market?: string | null;
  area?: string | null;
  listDate?: string | null;
  fullName?: string | null;
  website?: string | null;
  mainBusiness?: string | null;
  employees?: number | null;
  peRatio?: number | null;
  pbRatio?: number | null;
  totalMarketValue?: number | null;
  circulatingMarketValue?: number | null;
  belongBoards: string[];
}

export interface StockSearchResult {
  code: string;
  name: string;
  industry?: string | null;
}

export interface WatchlistAddResponse {
  added: number;
  watchlistTotal: number;
}

export interface WatchlistRemoveResponse {
  removed: string;
  watchlistTotal: number;
}

export interface WatchlistResponse {
  codes: string[];
}

export const stocksApi = {
  async extractFromImage(file: File): Promise<ExtractFromImageResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
    const response = await apiClient.post(
      '/api/v1/stocks/extract-from-image',
      formData,
      {
        headers,
        timeout: 60000, // Vision API can be slow; 60s
      },
    );

    const data = response.data as { codes?: string[]; raw_text?: string };
    return {
      codes: data.codes ?? [],
      rawText: data.raw_text,
    };
  },

  async getHistory(stockCode: string, days = 60, period = 'daily'): Promise<StockHistoryResponse> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/stocks/${encodeURIComponent(stockCode)}/history`, {
      params: { days, period },
    });
    return toCamelCase<StockHistoryResponse>(response.data);
  },

  async getIntraday(
    stockCode: string,
    interval = '1',
    limit = 240,
    includeTrades = true,
  ): Promise<StockIntradayResponse> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/stocks/${encodeURIComponent(stockCode)}/intraday`, {
      params: { interval, limit, include_trades: includeTrades },
    });
    return toCamelCase<StockIntradayResponse>(response.data);
  },

  async getFundFlow(stockCode: string, limit = 10): Promise<StockFundFlowResponse> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/stocks/${encodeURIComponent(stockCode)}/fund-flow`, {
      params: { limit },
    });
    return toCamelCase<StockFundFlowResponse>(response.data);
  },

  async getMeta(stockCode: string): Promise<StockMetaResponse> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/stocks/${encodeURIComponent(stockCode)}/meta`);
    return toCamelCase<StockMetaResponse>(response.data);
  },

  async searchStocks(q: string, limit = 10): Promise<StockSearchResult[]> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/stocks/search', {
      params: { q, limit },
    });
    const data = toCamelCase<{ results: StockSearchResult[] }>(response.data);
    return data.results;
  },

  async getWatchlist(): Promise<WatchlistResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/market/watchlist');
    return toCamelCase<WatchlistResponse>(response.data);
  },

  async addToWatchlist(codes: string[]): Promise<WatchlistAddResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/market/watchlist', { codes });
    return toCamelCase<WatchlistAddResponse>(response.data);
  },

  async removeFromWatchlist(code: string): Promise<WatchlistRemoveResponse> {
    const response = await apiClient.delete<Record<string, unknown>>(
      `/api/v1/market/watchlist/${encodeURIComponent(code)}`,
    );
    return toCamelCase<WatchlistRemoveResponse>(response.data);
  },
};
