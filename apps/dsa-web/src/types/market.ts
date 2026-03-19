export type MarketSessionState =
  | 'pre_open'
  | 'open'
  | 'midday_break'
  | 'after_close'
  | 'non_trading_day';

export type MarketWatchStatus = 'ok' | 'error';

export interface MarketPartialError {
  scope: string;
  target: string;
  message: string;
}

export interface MarketWatchlistItem {
  stockCode: string;
  stockName?: string | null;
  status: MarketWatchStatus;
  errorMessage?: string | null;
  currentPrice?: number | null;
  change?: number | null;
  changePercent?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  prevClose?: number | null;
  volume?: number | null;
  amount?: number | null;
  volumeRatio?: number | null;
  turnoverRate?: number | null;
  amplitude?: number | null;
  source?: string | null;
  pricePosition?: number | null;
}

export interface MarketIndexSnapshot {
  code: string;
  name: string;
  current?: number | null;
  change?: number | null;
  changePct?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  prevClose?: number | null;
  volume?: number | null;
  amount?: number | null;
  amplitude?: number | null;
}

export interface MarketStatsSnapshot {
  upCount?: number | null;
  downCount?: number | null;
  flatCount?: number | null;
  limitUpCount?: number | null;
  limitDownCount?: number | null;
  totalAmount?: number | null;
}

export interface SectorSnapshot {
  name: string;
  changePct?: number | null;
}

export interface SectorConstituentItem {
  stockCode: string;
  stockName?: string | null;
  industry?: string | null;
  area?: string | null;
  status: MarketWatchStatus;
  errorMessage?: string | null;
  currentPrice?: number | null;
  change?: number | null;
  changePercent?: number | null;
  volumeRatio?: number | null;
  turnoverRate?: number | null;
  amount?: number | null;
  source?: string | null;
}

export interface SectorConstituentResponse {
  sectorName: string;
  totalMatched: number;
  limit: number;
  updatedAt: string;
  constituents: SectorConstituentItem[];
  partialErrors: MarketPartialError[];
}

export interface MarketOverviewResponse {
  tradingDate: string;
  sessionState: MarketSessionState;
  realtimeEnabled: boolean;
  updatedAt: string;
  refreshIntervalSeconds: number;
  watchlistTotal: number;
  supportedTotal: number;
  unsupportedCodes: string[];
  watchlist: MarketWatchlistItem[];
  indices: MarketIndexSnapshot[];
  marketStats: MarketStatsSnapshot;
  topSectors: SectorSnapshot[];
  bottomSectors: SectorSnapshot[];
  partialErrors: MarketPartialError[];
}
