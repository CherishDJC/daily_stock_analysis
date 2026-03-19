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
};
