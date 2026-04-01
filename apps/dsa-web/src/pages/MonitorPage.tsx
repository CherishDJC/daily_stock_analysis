import type React from 'react';
import { useCallback, useDeferredValue, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { marketApi } from '../api/market';
import { stocksApi } from '../api/stocks';
import type { StockHistoryPoint, StockHistoryResponse, StockIntradayResponse, StockMinuteBar, StockSearchResult } from '../api/stocks';
import { Badge, Button, Card, Drawer, Select } from '../components/common';
import { useMonitorStore } from '../stores';
import type {
  MarketIndexSnapshot,
  MarketOverviewResponse,
  MarketPartialError,
  MarketSessionState,
  SectorConstituentResponse,
  MarketWatchlistItem,
  MarketStatsSnapshot,
  SectorSnapshot,
} from '../types/market';

type SortKey =
  | 'stockCode'
  | 'stockName'
  | 'currentPrice'
  | 'changePercent'
  | 'change'
  | 'amplitude'
  | 'volumeRatio'
  | 'turnoverRate'
  | 'amount'
  | 'source';

type SortDirection = 'asc' | 'desc';
type OverviewSection = 'watchlist' | 'summary';
type DailyKChartMode = 'preview' | 'fullscreen';
type PricePanelViewMode = 'minute' | 'daily';
type DailyKHoverState = {
  index: number;
  left: number;
  top: number;
};

const FEATURED_INDEX_CODES = ['sh000001', 'sz399001', 'sz399006', 'sh000300'];
const DAILY_K_DAYS_OPTIONS = [
  { value: '30', label: '近30日' },
  { value: '60', label: '近60日' },
  { value: '120', label: '近120日' },
];
const MINUTE_INTERVAL_OPTIONS = [
  { value: '1', label: '1分钟' },
  { value: '5', label: '5分钟' },
  { value: '15', label: '15分钟' },
  { value: '30', label: '30分钟' },
  { value: '60', label: '60分钟' },
];
const MINUTE_BAR_LIMITS: Record<string, number> = {
  '1': 240,
  '5': 240,
  '15': 180,
  '30': 160,
  '60': 120,
};
const SUMMARY_ERROR_SCOPES = new Set(['indices', 'market_stats', 'sector_rankings']);
const EMPTY_MARKET_STATS: MarketStatsSnapshot = {
  upCount: null,
  downCount: null,
  flatCount: null,
  limitUpCount: null,
  limitDownCount: null,
  totalAmount: null,
};
const EMPTY_OVERVIEW: MarketOverviewResponse = {
  tradingDate: '--',
  sessionState: 'non_trading_day',
  realtimeEnabled: true,
  updatedAt: '',
  refreshIntervalSeconds: 0,
  watchlistTotal: 0,
  supportedTotal: 0,
  unsupportedCodes: [],
  watchlist: [],
  indices: [],
  marketStats: EMPTY_MARKET_STATS,
  topSectors: [],
  bottomSectors: [],
  partialErrors: [],
};
const EMPTY_SECTOR_CONSTITUENTS: SectorConstituentResponse = {
  sectorName: '',
  totalMatched: 0,
  limit: 10,
  updatedAt: '',
  constituents: [],
  partialErrors: [],
};

function formatSigned(value?: number | null, digits = 2, suffix = ''): string {
  if (value == null) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}${suffix}`;
}

function formatPlain(value?: number | null, digits = 2, suffix = ''): string {
  if (value == null) return '--';
  return `${value.toFixed(digits)}${suffix}`;
}

function formatAmount(value?: number | null): string {
  if (value == null) return '--';
  const absValue = Math.abs(value);
  if (absValue >= 1e8) {
    return `${(value / 1e8).toFixed(2)}亿`;
  }
  if (absValue >= 1e4) {
    return `${(value / 1e4).toFixed(2)}万`;
  }
  return value.toFixed(0);
}

function formatUpdatedAt(value?: string | null): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatDateLabel(value?: string | null): string {
  if (!value) return '--';
  const parts = value.split('-');
  if (parts.length !== 3) return value;
  return `${parts[1]}-${parts[2]}`;
}

function formatDateTimeLabel(value?: string | null): string {
  if (!value) return '--';
  const date = new Date(value.replace(' ', 'T'));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatMinuteAxisLabel(value?: string | null): string {
  if (!value) return '--';
  const date = new Date(value.replace(' ', 'T'));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function resolveHistoryChangePercent(points: StockHistoryPoint[], index: number): number | null {
  const point = points[index];
  if (!point) return null;
  if (point.changePercent != null) return point.changePercent;
  if (index === 0) return null;

  const previousClose = points[index - 1]?.close;
  if (!previousClose) return null;
  return ((point.close - previousClose) / previousClose) * 100;
}

function resolveMinuteChangePercent(points: StockMinuteBar[], index: number): number | null {
  const point = points[index];
  if (!point) return null;
  if (point.changePercent != null) return point.changePercent;
  if (index === 0) return null;

  const previousClose = points[index - 1]?.close;
  if (!previousClose) return null;
  return ((point.close - previousClose) / previousClose) * 100;
}

function badgeVariantForSession(sessionState: MarketSessionState): 'info' | 'warning' | 'danger' | 'success' {
  if (sessionState === 'open') return 'success';
  if (sessionState === 'midday_break') return 'warning';
  if (sessionState === 'non_trading_day') return 'danger';
  return 'info';
}

function sessionLabel(sessionState: MarketSessionState): string {
  switch (sessionState) {
    case 'open':
      return '盘中';
    case 'pre_open':
      return '开盘前';
    case 'midday_break':
      return '午间休市';
    case 'after_close':
      return '已收盘';
    case 'non_trading_day':
      return '非交易日';
    default:
      return sessionState;
  }
}

function textClassForChange(value?: number | null): string {
  if (value == null) return 'text-secondary';
  if (value > 0) return 'text-red-400';
  if (value < 0) return 'text-emerald-400';
  return 'text-secondary';
}

function mergePartialErrors(
  currentErrors: MarketPartialError[],
  nextErrors: MarketPartialError[],
  section: OverviewSection,
): MarketPartialError[] {
  const shouldReplace = (item: MarketPartialError) =>
    section === 'watchlist' ? item.scope.startsWith('watchlist_') : SUMMARY_ERROR_SCOPES.has(item.scope);

  const retainedErrors = currentErrors.filter((item) => !shouldReplace(item));
  const scopedErrors = nextErrors.filter((item) => shouldReplace(item));
  return [...retainedErrors, ...scopedErrors];
}

function mergeOverview(
  current: MarketOverviewResponse,
  next: MarketOverviewResponse,
  section: OverviewSection,
): MarketOverviewResponse {
  const sharedState = {
    tradingDate: next.tradingDate,
    sessionState: next.sessionState,
    realtimeEnabled: next.realtimeEnabled,
    updatedAt: next.updatedAt,
    refreshIntervalSeconds: next.refreshIntervalSeconds,
    watchlistTotal: next.watchlistTotal,
    supportedTotal: next.supportedTotal,
    unsupportedCodes: next.unsupportedCodes,
  };

  if (section === 'watchlist') {
    return {
      ...current,
      ...sharedState,
      watchlist: next.watchlist,
      partialErrors: mergePartialErrors(current.partialErrors, next.partialErrors, 'watchlist'),
    };
  }

  return {
    ...current,
    ...sharedState,
    indices: next.indices,
    marketStats: next.marketStats,
    topSectors: next.topSectors,
    bottomSectors: next.bottomSectors,
    partialErrors: mergePartialErrors(current.partialErrors, next.partialErrors, 'summary'),
  };
}

function sortWatchlist(
  rows: MarketWatchlistItem[],
  sortKey: SortKey,
  sortDirection: SortDirection,
  keyword: string,
): MarketWatchlistItem[] {
  const normalizedKeyword = keyword.trim().toLowerCase();
  const filteredRows = normalizedKeyword
    ? rows.filter((item) => {
        const haystack = [
          item.stockCode,
          item.stockName || '',
          item.source || '',
          item.errorMessage || '',
        ]
          .join(' ')
          .toLowerCase();
        return haystack.includes(normalizedKeyword);
      })
    : rows;

  const multiplier = sortDirection === 'asc' ? 1 : -1;
  return [...filteredRows].sort((left, right) => {
    if (left.status !== right.status) {
      return left.status === 'error' ? 1 : -1;
    }

    const leftValue = left[sortKey];
    const rightValue = right[sortKey];

    if (typeof leftValue === 'string' || typeof rightValue === 'string') {
      return String(leftValue || '').localeCompare(String(rightValue || ''), 'zh-CN') * multiplier;
    }

    const leftNumber = typeof leftValue === 'number' ? leftValue : Number.NEGATIVE_INFINITY;
    const rightNumber = typeof rightValue === 'number' ? rightValue : Number.NEGATIVE_INFINITY;
    if (leftNumber === rightNumber) {
      return left.stockCode.localeCompare(right.stockCode, 'zh-CN');
    }
    return (leftNumber - rightNumber) * multiplier;
  });
}

const MetricStat: React.FC<{ label: string; value: string; accent?: 'up' | 'down' | 'neutral' }> = ({
  label,
  value,
  accent = 'neutral',
}) => {
  const accentClass =
    accent === 'up'
      ? 'text-red-400'
      : accent === 'down'
        ? 'text-emerald-400'
        : 'text-white';

  return (
    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-2">
      <p className="text-[11px] uppercase tracking-[0.24em] text-muted">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${accentClass}`}>{value}</p>
    </div>
  );
};

const IndexCard: React.FC<{ indexData?: MarketIndexSnapshot; fallbackName: string; isLoading?: boolean }> = ({
  indexData,
  fallbackName,
  isLoading = false,
}) => {
  const changePct = indexData?.changePct;
  const changeClass = textClassForChange(changePct);

  return (
    <Card variant="gradient" padding="md" className="min-h-[144px]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="label-uppercase">{indexData?.code || 'N/A'}</span>
          <h3 className="mt-1 text-lg font-semibold text-white">{indexData?.name || fallbackName}</h3>
        </div>
        <Badge variant={indexData ? 'info' : 'warning'}>{indexData ? '实时' : isLoading ? '加载中' : '缺失'}</Badge>
      </div>
      <div className="mt-5 space-y-2">
        <p className="text-3xl font-semibold tracking-tight text-white">
          {indexData?.current != null ? indexData.current.toFixed(2) : '--'}
        </p>
        <div className={`flex items-center gap-2 text-sm font-medium ${changeClass}`}>
          <span>{formatSigned(indexData?.change, 2)}</span>
          <span>{formatSigned(indexData?.changePct, 2, '%')}</span>
        </div>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-2 text-xs text-secondary">
        <div>振幅 {formatPlain(indexData?.amplitude, 2, '%')}</div>
        <div>成交额 {formatAmount(indexData?.amount)}</div>
      </div>
    </Card>
  );
};

const SectorList: React.FC<{
  title: string;
  sectors: SectorSnapshot[];
  positive: boolean;
  isLoading?: boolean;
  onSelect?: (sector: SectorSnapshot) => void;
  selectedSectorName?: string | null;
}> = ({
  title,
  sectors,
  positive,
  isLoading = false,
  onSelect,
  selectedSectorName,
}) => (
  <div className="rounded-xl border border-white/8 bg-black/20 p-3">
    <div className="mb-3 flex items-center justify-between">
      <span className="label-uppercase">{title}</span>
      <Badge variant={positive ? 'success' : 'danger'}>{sectors.length || 0}</Badge>
    </div>
    <div className="space-y-2">
      {sectors.length ? (
        sectors.map((sector) => (
          <button
            key={`${title}-${sector.name}`}
            type="button"
            onClick={() => onSelect?.(sector)}
            className={`flex w-full items-center justify-between rounded-xl border px-3 py-2 text-sm transition ${
              selectedSectorName === sector.name
                ? 'border-cyan/35 bg-cyan/10'
                : 'border-white/6 bg-black/10 hover:border-cyan/20 hover:bg-white/4'
            }`}
          >
            <span className="truncate text-left text-secondary">{sector.name}</span>
            <span className={`ml-3 whitespace-nowrap ${positive ? 'text-red-400' : 'text-emerald-400'}`}>
              {formatSigned(sector.changePct, 2, '%')}
            </span>
          </button>
        ))
      ) : (
        <p className="text-sm text-muted">{isLoading ? '板块数据加载中...' : '暂无板块数据'}</p>
      )}
    </div>
  </div>
);

const ErrorStrip: React.FC<{ errors: MarketPartialError[] }> = ({ errors }) => {
  if (!errors.length) return null;

  return (
    <Card variant="bordered" padding="md" className="border-amber-500/20 bg-amber-500/5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <span className="label-uppercase">PARTIAL DEGRADATION</span>
          <h3 className="mt-1 text-base font-semibold text-white">部分数据源降级，页面仍可继续使用</h3>
        </div>
        <Badge variant="warning">{errors.length}</Badge>
      </div>
      <div className="mt-4 space-y-2 text-sm">
        {errors.slice(0, 5).map((item) => (
          <div key={`${item.scope}-${item.target}`} className="rounded-xl border border-white/8 bg-black/20 px-3 py-2">
            <p className="font-medium text-white">
              {item.scope} / {item.target}
            </p>
            <p className="mt-1 text-secondary">{item.message}</p>
          </div>
        ))}
      </div>
    </Card>
  );
};

const DailyKChart: React.FC<{
  points: StockHistoryPoint[];
  mode?: DailyKChartMode;
  onRequestFullscreen?: () => void;
}> = ({ points, mode = 'preview', onRequestFullscreen }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hoveredBar, setHoveredBar] = useState<DailyKHoverState | null>(null);

  if (!points.length) {
    return (
      <div className="flex h-[320px] items-center justify-center rounded-2xl border border-dashed border-white/12 bg-black/20 text-sm text-secondary">
        暂无日 K 数据
      </div>
    );
  }

  const isFullscreen = mode === 'fullscreen';
  const width = isFullscreen ? 1440 : 820;
  const height = isFullscreen ? 720 : 320;
  const padding = isFullscreen
    ? { top: 30, right: 28, bottom: 52, left: 72 }
    : { top: 20, right: 20, bottom: 34, left: 54 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const highs = points.map((item) => item.high);
  const lows = points.map((item) => item.low);
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const priceRange = Math.max(maxPrice - minPrice, 0.01);
  const stepX = innerWidth / Math.max(points.length, 1);
  const candleWidth = Math.max(Math.min(stepX * (isFullscreen ? 0.62 : 0.56), isFullscreen ? 16 : 10), 3);

  const toY = (price: number) => padding.top + ((maxPrice - price) / priceRange) * innerHeight;
  const hoveredPoint = hoveredBar ? points[hoveredBar.index] : null;
  const hoveredChangePercent = hoveredBar ? resolveHistoryChangePercent(points, hoveredBar.index) : null;
  const hoveredX = hoveredBar ? padding.left + stepX * hoveredBar.index + stepX / 2 : null;
  const labelIndexes = (isFullscreen
    ? [0, Math.floor((points.length - 1) / 4), Math.floor((points.length - 1) / 2), Math.floor(((points.length - 1) * 3) / 4), points.length - 1]
    : [0, Math.floor((points.length - 1) / 2), points.length - 1]
  ).filter((value, index, array) => array.indexOf(value) === index);

  const updateHoverState = (event: React.PointerEvent<SVGRectElement>, index: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;

    const left = Math.max(92, Math.min(event.clientX - rect.left, rect.width - 92));
    const top = Math.max(isFullscreen ? 120 : 92, Math.min(event.clientY - rect.top, rect.height - 28));
    setHoveredBar({ index, left, top });
  };

  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden rounded-2xl border ${
        isFullscreen
          ? 'h-full border-cyan/20 bg-[linear-gradient(180deg,rgba(3,8,18,0.96),rgba(2,5,10,0.98))] p-4 shadow-[0_24px_80px_rgba(0,0,0,0.42)]'
          : 'border-white/8 bg-black/20 p-3'
      }`}
    >
      {onRequestFullscreen ? (
        <button
          type="button"
          onClick={onRequestFullscreen}
          className="absolute right-3 top-3 z-20 inline-flex items-center gap-2 rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-xs font-medium text-cyan-300 transition hover:border-cyan/50 hover:bg-cyan/15 hover:text-white"
        >
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 3H5a2 2 0 00-2 2v3m16-5h-3m3 0v3m0 13h-3m3 0v-3M5 21h3m-3 0v-3" />
          </svg>
          全屏查看
        </button>
      ) : null}

      {hoveredPoint ? (
        <div
          className="pointer-events-none absolute z-20 min-w-[196px] rounded-2xl border border-white/12 bg-[#04070d]/95 px-3 py-3 shadow-[0_18px_56px_rgba(0,0,0,0.48)]"
          style={{
            left: hoveredBar?.left ?? 0,
            top: hoveredBar?.top ?? 0,
            transform: 'translate(-50%, calc(-100% - 14px))',
          }}
        >
          <p className="text-[11px] uppercase tracking-[0.24em] text-muted">BAR DETAIL</p>
          <p className="mt-2 text-sm font-semibold text-white">{hoveredPoint.date}</p>
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <span className="text-muted">收盘</span>
            <span className="text-right font-medium text-white">{hoveredPoint.close.toFixed(2)}</span>
            <span className="text-muted">涨跌幅</span>
            <span className={`text-right font-medium ${textClassForChange(hoveredChangePercent)}`}>
              {formatSigned(hoveredChangePercent, 2, '%')}
            </span>
            <span className="text-muted">开 / 高</span>
            <span className="text-right text-secondary">
              {hoveredPoint.open.toFixed(2)} / {hoveredPoint.high.toFixed(2)}
            </span>
            <span className="text-muted">低 / 收</span>
            <span className="text-right text-secondary">
              {hoveredPoint.low.toFixed(2)} / {hoveredPoint.close.toFixed(2)}
            </span>
          </div>
        </div>
      ) : null}

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className={isFullscreen ? 'h-full w-full' : 'h-[320px] w-full'}
        role="img"
        aria-label="Daily K chart"
        onPointerLeave={() => setHoveredBar(null)}
      >
        {Array.from({ length: 5 }).map((_, index) => {
          const price = maxPrice - (priceRange / 4) * index;
          const y = toY(price);
          return (
            <g key={`grid-${index}`}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="rgba(255,255,255,0.08)" strokeDasharray="4 4" />
              <text x={10} y={y + 4} fill="rgba(255,255,255,0.56)" fontSize="11">
                {price.toFixed(2)}
              </text>
            </g>
          );
        })}

        {hoveredBar && hoveredX != null ? (
          <>
            <rect
              x={padding.left + stepX * hoveredBar.index}
              y={padding.top}
              width={stepX}
              height={innerHeight}
              fill="rgba(34,211,238,0.06)"
            />
            <line
              x1={hoveredX}
              x2={hoveredX}
              y1={padding.top}
              y2={height - padding.bottom}
              stroke="rgba(34,211,238,0.38)"
              strokeDasharray="5 5"
            />
          </>
        ) : null}

        {points.map((item, index) => {
          const x = padding.left + stepX * index + stepX / 2;
          const openY = toY(item.open);
          const closeY = toY(item.close);
          const highY = toY(item.high);
          const lowY = toY(item.low);
          const isUp = item.close >= item.open;
          const color = isUp ? '#f87171' : '#34d399';
          const bodyY = Math.min(openY, closeY);
          const bodyHeight = Math.max(Math.abs(closeY - openY), 1.5);

          return (
            <g key={item.date}>
              <line x1={x} x2={x} y1={highY} y2={lowY} stroke={color} strokeWidth="1.2" />
              <rect
                x={x - candleWidth / 2}
                y={bodyY}
                width={candleWidth}
                height={bodyHeight}
                rx="1"
                fill={isUp ? color : 'transparent'}
                stroke={color}
                strokeWidth="1"
              />
            </g>
          );
        })}

        {points.map((item, index) => (
          <rect
            key={`hover-zone-${item.date}`}
            x={padding.left + stepX * index}
            y={padding.top}
            width={stepX}
            height={innerHeight}
            fill="transparent"
            pointerEvents="all"
            onPointerEnter={(event) => updateHoverState(event, index)}
            onPointerMove={(event) => updateHoverState(event, index)}
          />
        ))}

        {labelIndexes.map((index) => {
          const x = padding.left + stepX * index + stepX / 2;
          return (
            <text
              key={`label-${points[index].date}`}
              x={x}
              y={height - 10}
              textAnchor="middle"
              fill="rgba(255,255,255,0.56)"
              fontSize={isFullscreen ? '12' : '11'}
            >
              {formatDateLabel(points[index].date)}
            </text>
          );
        })}
      </svg>
    </div>
  );
};

const MinutePulseChart: React.FC<{
  bars: StockMinuteBar[];
  mode?: DailyKChartMode;
  onRequestFullscreen?: () => void;
}> = ({ bars, mode = 'preview', onRequestFullscreen }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hoveredBar, setHoveredBar] = useState<DailyKHoverState | null>(null);

  if (!bars.length) {
    return (
      <div className="flex h-[360px] items-center justify-center rounded-2xl border border-dashed border-white/12 bg-black/20 text-sm text-secondary">
        暂无分时数据
      </div>
    );
  }

  const isFullscreen = mode === 'fullscreen';
  const width = isFullscreen ? 1440 : 820;
  const height = isFullscreen ? 720 : 360;
  const padding = isFullscreen
    ? { top: 30, right: 28, bottom: 54, left: 72 }
    : { top: 22, right: 20, bottom: 42, left: 54 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const priceHeight = innerHeight * 0.76;
  const volumeHeight = innerHeight * 0.18;
  const volumeTop = padding.top + priceHeight + 12;
  const closes = bars.map((item) => item.close);
  const maxPrice = Math.max(...bars.map((item) => item.high));
  const minPrice = Math.min(...bars.map((item) => item.low));
  const priceRange = Math.max(maxPrice - minPrice, 0.01);
  const volumeMax = Math.max(...bars.map((item) => item.volume ?? 0), 1);
  const stepX = innerWidth / Math.max(bars.length - 1, 1);
  const toX = (index: number) => padding.left + stepX * index;
  const toPriceY = (price: number) => padding.top + ((maxPrice - price) / priceRange) * priceHeight;
  const toVolumeY = (volume?: number | null) => {
    const normalized = Math.max((volume ?? 0) / volumeMax, 0);
    return volumeTop + volumeHeight - normalized * volumeHeight;
  };

  const linePath = bars
    .map((item, index) => `${index === 0 ? 'M' : 'L'} ${toX(index)} ${toPriceY(item.close)}`)
    .join(' ');
  const areaPath = `${linePath} L ${toX(bars.length - 1)} ${volumeTop + volumeHeight} L ${toX(0)} ${volumeTop + volumeHeight} Z`;
  const hoveredPoint = hoveredBar ? bars[hoveredBar.index] : null;
  const hoveredChangePercent = hoveredBar ? resolveMinuteChangePercent(bars, hoveredBar.index) : null;
  const labelIndexes = (isFullscreen
    ? [0, Math.floor((bars.length - 1) / 4), Math.floor((bars.length - 1) / 2), Math.floor(((bars.length - 1) * 3) / 4), bars.length - 1]
    : [0, Math.floor((bars.length - 1) / 2), bars.length - 1]
  ).filter((value, index, array) => array.indexOf(value) === index);

  const updateHoverState = (event: React.PointerEvent<SVGRectElement>, index: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;

    const left = Math.max(96, Math.min(event.clientX - rect.left, rect.width - 96));
    const top = Math.max(isFullscreen ? 126 : 96, Math.min(event.clientY - rect.top, rect.height - 32));
    setHoveredBar({ index, left, top });
  };

  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden rounded-2xl border ${
        isFullscreen
          ? 'h-full border-cyan/20 bg-[linear-gradient(180deg,rgba(3,8,18,0.96),rgba(2,5,10,0.98))] p-4 shadow-[0_24px_80px_rgba(0,0,0,0.42)]'
          : 'border-white/8 bg-black/20 p-3'
      }`}
    >
      {onRequestFullscreen ? (
        <button
          type="button"
          onClick={onRequestFullscreen}
          className="absolute right-3 top-3 z-20 inline-flex items-center gap-2 rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-xs font-medium text-cyan-300 transition hover:border-cyan/50 hover:bg-cyan/15 hover:text-white"
        >
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 3H5a2 2 0 00-2 2v3m16-5h-3m3 0v3m0 13h-3m3 0v-3M5 21h3m-3 0v-3" />
          </svg>
          全屏查看
        </button>
      ) : null}

      {hoveredPoint ? (
        <div
          className="pointer-events-none absolute z-20 min-w-[212px] rounded-2xl border border-white/12 bg-[#04070d]/95 px-3 py-3 shadow-[0_18px_56px_rgba(0,0,0,0.48)]"
          style={{
            left: hoveredBar?.left ?? 0,
            top: hoveredBar?.top ?? 0,
            transform: 'translate(-50%, calc(-100% - 14px))',
          }}
        >
          <p className="text-[11px] uppercase tracking-[0.24em] text-muted">INTRADAY BAR</p>
          <p className="mt-2 text-sm font-semibold text-white">{formatDateTimeLabel(hoveredPoint.timestamp)}</p>
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <span className="text-muted">现价</span>
            <span className="text-right font-medium text-white">{hoveredPoint.close.toFixed(2)}</span>
            <span className="text-muted">较前一根</span>
            <span className={`text-right font-medium ${textClassForChange(hoveredChangePercent)}`}>
              {formatSigned(hoveredChangePercent, 2, '%')}
            </span>
            <span className="text-muted">开 / 高</span>
            <span className="text-right text-secondary">
              {hoveredPoint.open.toFixed(2)} / {hoveredPoint.high.toFixed(2)}
            </span>
            <span className="text-muted">低 / 收</span>
            <span className="text-right text-secondary">
              {hoveredPoint.low.toFixed(2)} / {hoveredPoint.close.toFixed(2)}
            </span>
          </div>
        </div>
      ) : null}

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className={isFullscreen ? 'h-full w-full' : 'h-[360px] w-full'}
        role="img"
        aria-label="Intraday chart"
        onPointerLeave={() => setHoveredBar(null)}
      >
        {Array.from({ length: 4 }).map((_, index) => {
          const price = maxPrice - (priceRange / 3) * index;
          const y = toPriceY(price);
          return (
            <g key={`minute-grid-${index}`}>
              <line
                x1={padding.left}
                x2={width - padding.right}
                y1={y}
                y2={y}
                stroke="rgba(255,255,255,0.08)"
                strokeDasharray="4 4"
              />
              <text x={10} y={y + 4} fill="rgba(255,255,255,0.56)" fontSize="11">
                {price.toFixed(2)}
              </text>
            </g>
          );
        })}

        <path d={areaPath} fill="url(#minute-area-fill)" opacity="0.92" />
        <path d={linePath} fill="none" stroke="#22d3ee" strokeWidth={isFullscreen ? 2.6 : 2.1} strokeLinejoin="round" strokeLinecap="round" />

        {bars.map((item, index) => {
          const previousClose = index > 0 ? bars[index - 1].close : bars[0].open;
          const barColor = item.close >= previousClose ? '#f87171' : '#34d399';
          const barWidth = Math.max(isFullscreen ? 3.4 : 2.4, stepX * 0.52);
          return (
            <rect
              key={`volume-${item.timestamp}`}
              x={toX(index) - barWidth / 2}
              y={toVolumeY(item.volume)}
              width={barWidth}
              height={Math.max(volumeTop + volumeHeight - toVolumeY(item.volume), 1)}
              rx="1"
              fill={barColor}
              opacity="0.68"
            />
          );
        })}

        {hoveredBar ? (
          <>
            <rect
              x={toX(hoveredBar.index) - stepX / 2}
              y={padding.top}
              width={Math.max(stepX, 6)}
              height={innerHeight}
              fill="rgba(34,211,238,0.06)"
            />
            <line
              x1={toX(hoveredBar.index)}
              x2={toX(hoveredBar.index)}
              y1={padding.top}
              y2={height - padding.bottom}
              stroke="rgba(34,211,238,0.38)"
              strokeDasharray="5 5"
            />
            <circle cx={toX(hoveredBar.index)} cy={toPriceY(closes[hoveredBar.index])} r={isFullscreen ? 4.5 : 3.5} fill="#22d3ee" />
          </>
        ) : null}

        {bars.map((item, index) => (
          <rect
            key={`minute-hover-zone-${item.timestamp}`}
            x={toX(index) - Math.max(stepX, 6) / 2}
            y={padding.top}
            width={Math.max(stepX, 6)}
            height={innerHeight}
            fill="transparent"
            pointerEvents="all"
            onPointerEnter={(event) => updateHoverState(event, index)}
            onPointerMove={(event) => updateHoverState(event, index)}
          />
        ))}

        {labelIndexes.map((index) => (
          <text
            key={`minute-label-${bars[index].timestamp}`}
            x={toX(index)}
            y={height - 10}
            textAnchor="middle"
            fill="rgba(255,255,255,0.56)"
            fontSize={isFullscreen ? '12' : '11'}
          >
            {formatMinuteAxisLabel(bars[index].timestamp)}
          </text>
        ))}

        <defs>
          <linearGradient id="minute-area-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.26" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.01" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  );
};

const DailyKTable: React.FC<{ points: StockHistoryPoint[] }> = ({ points }) => {
  const recentPoints = [...points].slice(-8).reverse();

  return (
    <div className="overflow-x-auto rounded-2xl border border-white/8 bg-black/20">
      <table className="min-w-full border-separate border-spacing-0">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-[0.2em] text-muted">
            <th className="px-4 py-3">日期</th>
            <th className="px-4 py-3">开</th>
            <th className="px-4 py-3">高</th>
            <th className="px-4 py-3">低</th>
            <th className="px-4 py-3">收</th>
            <th className="px-4 py-3">涨跌幅</th>
          </tr>
        </thead>
        <tbody>
          {recentPoints.map((item) => (
            <tr key={`kline-row-${item.date}`} className="border-t border-white/6 text-sm text-secondary">
              <td className="px-4 py-3 text-white">{item.date}</td>
              <td className="px-4 py-3">{item.open.toFixed(2)}</td>
              <td className="px-4 py-3">{item.high.toFixed(2)}</td>
              <td className="px-4 py-3">{item.low.toFixed(2)}</td>
              <td className={`px-4 py-3 font-medium ${textClassForChange((item.close ?? 0) - (item.open ?? 0))}`}>
                {item.close.toFixed(2)}
              </td>
              <td className={`px-4 py-3 ${textClassForChange(item.changePercent)}`}>
                {formatSigned(item.changePercent, 2, '%')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const SectorConstituentDrawer: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  sectorName?: string | null;
  detail: SectorConstituentResponse;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
  onOpenStock: (item: { stockCode: string; stockName?: string | null }) => void;
}> = ({ isOpen, onClose, sectorName, detail, isLoading, error, onRefresh, onOpenStock }) => {
  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={sectorName ? `${sectorName} 相关股` : '板块相关股'}
      width="max-w-4xl"
    >
      <div className="space-y-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <span className="label-uppercase">SECTOR DRILL-DOWN</span>
            <h3 className="mt-1 text-2xl font-semibold text-white">{sectorName || '--'}</h3>
            <p className="mt-2 text-sm text-secondary">
              展示最多 10 只行业相关股，点击任意股票可继续查看分时与日 K 走势。
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="info">命中 {detail.totalMatched}</Badge>
            <Badge variant="default">最多显示 {detail.limit}</Badge>
            <Button variant="outline" isLoading={isLoading} onClick={onRefresh}>
              刷新相关股
            </Button>
          </div>
        </div>

        {error ? (
          <Card variant="bordered" padding="md" className="border-red-500/30 bg-red-500/5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="label-uppercase">SECTOR FAILED</span>
                <p className="mt-1 text-sm text-secondary">{error}</p>
              </div>
              <Button variant="danger" onClick={onRefresh}>
                重试
              </Button>
            </div>
          </Card>
        ) : null}

        {detail.partialErrors.length ? <ErrorStrip errors={detail.partialErrors} /> : null}

        {isLoading && !detail.constituents.length ? (
          <div className="flex h-[240px] items-center justify-center rounded-2xl border border-white/8 bg-black/20 text-sm text-secondary">
            相关股加载中...
          </div>
        ) : detail.constituents.length ? (
          <div className="overflow-x-auto rounded-2xl border border-white/8 bg-black/20">
            <table className="min-w-full border-separate border-spacing-0">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-[0.2em] text-muted">
                  <th className="px-4 py-3">代码 / 名称</th>
                  <th className="px-4 py-3">最新价</th>
                  <th className="px-4 py-3">涨跌幅</th>
                  <th className="px-4 py-3">涨跌额</th>
                  <th className="px-4 py-3">量比</th>
                  <th className="px-4 py-3">换手率</th>
                  <th className="px-4 py-3">成交额</th>
                  <th className="px-4 py-3">数据源</th>
                </tr>
              </thead>
              <tbody>
                {detail.constituents.map((item) => (
                  <tr
                    key={`sector-stock-${item.stockCode}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => onOpenStock({ stockCode: item.stockCode, stockName: item.stockName })}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onOpenStock({ stockCode: item.stockCode, stockName: item.stockName });
                      }
                    }}
                    className={`cursor-pointer border-t border-white/6 text-sm transition hover:bg-white/4 ${
                      item.status === 'error' ? 'bg-red-500/[0.03]' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div>
                          <p className="font-semibold text-white">{item.stockCode}</p>
                          <p className="mt-1 text-xs text-secondary">{item.stockName || item.industry || '--'}</p>
                        </div>
                        <Badge variant={item.status === 'ok' ? 'success' : 'danger'}>
                          {item.status === 'ok' ? '正常' : '失败'}
                        </Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-white">
                      {item.currentPrice != null ? item.currentPrice.toFixed(2) : '--'}
                    </td>
                    <td className={`px-4 py-3 ${textClassForChange(item.changePercent)}`}>
                      {formatSigned(item.changePercent, 2, '%')}
                    </td>
                    <td className={`px-4 py-3 ${textClassForChange(item.change)}`}>
                      {formatSigned(item.change, 2)}
                    </td>
                    <td className="px-4 py-3 text-secondary">{formatPlain(item.volumeRatio, 2)}</td>
                    <td className="px-4 py-3 text-secondary">{formatPlain(item.turnoverRate, 2, '%')}</td>
                    <td className="px-4 py-3 text-secondary">{formatAmount(item.amount)}</td>
                    <td className="px-4 py-3">
                      <Badge variant={item.source ? 'info' : 'default'}>{item.source || '--'}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex h-[220px] items-center justify-center rounded-2xl border border-dashed border-white/12 bg-black/20 text-sm text-secondary">
            暂无相关股数据
          </div>
        )}
      </div>
    </Drawer>
  );
};

const PriceChartFullscreenOverlay: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  viewMode: PricePanelViewMode;
  dailyLoading: boolean;
  dailyPoints: StockHistoryPoint[];
  intradayLoading: boolean;
  minuteBars: StockMinuteBar[];
}> = ({
  isOpen,
  onClose,
  viewMode,
  dailyLoading,
  dailyPoints,
  intradayLoading,
  minuteBars,
}) => {
  if (!isOpen) return null;

  const isMinuteView = viewMode === 'minute';
  const isLoading = isMinuteView ? intradayLoading : dailyLoading;
  const hasData = isMinuteView ? minuteBars.length > 0 : dailyPoints.length > 0;
  const emptyLabel = isMinuteView ? '暂无分时数据' : '暂无日 K 数据';

  return (
    <div className="fixed inset-0 z-[70] bg-[rgba(2,6,12,0.96)] backdrop-blur-md" onClick={onClose}>
      <div
        className="relative h-full w-full p-3 md:p-4"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="relative h-full overflow-hidden rounded-[28px] border border-cyan/18 bg-[radial-gradient(circle_at_top_left,rgba(0,212,255,0.08),transparent_32%),linear-gradient(180deg,rgba(6,11,19,0.98),rgba(3,8,15,1))] shadow-[0_32px_90px_rgba(0,0,0,0.42)]">
          <Button
            size="sm"
            variant="secondary"
            onClick={onClose}
            className="absolute right-4 top-4 z-20 shadow-[0_14px_36px_rgba(0,0,0,0.32)]"
          >
            退出全屏
          </Button>

          <div className="h-full p-2 md:p-3">
            {isLoading && !hasData ? (
              <div className="flex h-full items-center justify-center rounded-[24px] border border-white/10 bg-black/35 text-sm text-secondary">
                {isMinuteView ? '分时加载中...' : '日K 加载中...'}
              </div>
            ) : !hasData ? (
              <div className="flex h-full items-center justify-center rounded-[24px] border border-dashed border-white/12 bg-black/35 text-sm text-secondary">
                {emptyLabel}
              </div>
            ) : (
              <>
                {isMinuteView ? (
                  <MinutePulseChart bars={minuteBars} mode="fullscreen" />
                ) : (
                  <DailyKChart points={dailyPoints} mode="fullscreen" />
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

const MonitorPage: React.FC = () => {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<MarketOverviewResponse>(EMPTY_OVERVIEW);
  const [watchlistLoading, setWatchlistLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [watchlistLoaded, setWatchlistLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [searchResults, setSearchResults] = useState<StockSearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchFocused, setSearchFocused] = useState(false);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchRequestIdRef = useRef(0);
  const [sortKey, setSortKey] = useState<SortKey>('changePercent');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [selectedSector, setSelectedSector] = useState<SectorSnapshot | null>(null);
  const [sectorDrawerVisible, setSectorDrawerVisible] = useState(false);
  const [resumeSectorDrawerAfterDailyK, setResumeSectorDrawerAfterDailyK] = useState(false);
  const [sectorDetail, setSectorDetail] = useState<SectorConstituentResponse>(EMPTY_SECTOR_CONSTITUENTS);
  const [sectorDetailLoading, setSectorDetailLoading] = useState(false);
  const [sectorDetailError, setSectorDetailError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyData, setHistoryData] = useState<StockHistoryResponse | null>(null);
  const [historyLoadedKey, setHistoryLoadedKey] = useState('');
  const [intradayLoading, setIntradayLoading] = useState(false);
  const [intradayError, setIntradayError] = useState<string | null>(null);
  const [intradayData, setIntradayData] = useState<StockIntradayResponse | null>(null);
  const [intradayLoadedKey, setIntradayLoadedKey] = useState('');
  const [restoredNoticeVisible, setRestoredNoticeVisible] = useState(false);
  const {
    selectedStock,
    setSelectedStock,
    pricePanelViewMode,
    setPricePanelViewMode,
    historyDays,
    setHistoryDays,
    minuteInterval,
    setMinuteInterval,
    historyFullscreen,
    setHistoryFullscreen,
    resetDetail,
  } = useMonitorStore();
  const sessionStateRef = useRef<MarketSessionState | null>(null);
  const autoRefreshInitializedRef = useRef(false);
  const overviewRef = useRef<MarketOverviewResponse>(EMPTY_OVERVIEW);
  const historyRequestIdRef = useRef(0);
  const intradayRequestIdRef = useRef(0);
  const sectorRequestIdRef = useRef(0);

  useEffect(() => {
    overviewRef.current = overview;
  }, [overview]);

  useEffect(() => {
    if (!selectedStock) return;
    setRestoredNoticeVisible(true);
    const timer = window.setTimeout(() => {
      setRestoredNoticeVisible(false);
    }, 2800);
    return () => window.clearTimeout(timer);
  }, []);

  // ---- Watchlist data fetching ----
  const fetchWatchlistOverview = useCallback(async (forceRefresh = false) => {
    setWatchlistLoading(true);
    try {
      const nextOverview = await marketApi.getOverview(forceRefresh, {
        includeWatchlist: true,
        includeSummary: false,
      });
      setOverview((current) => mergeOverview(current, nextOverview, 'watchlist'));
      setError(null);
      setWatchlistLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载实时看盘失败');
    } finally {
      setWatchlistLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchWatchlistOverview();
  }, [fetchWatchlistOverview]);

  // ---- Stock search ----
  useEffect(() => {
    const q = deferredSearch.trim();
    const requestId = ++searchRequestIdRef.current;
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!q) {
      setSearchResults([]);
      setSearchLoading(false);
      return;
    }
    setSearchLoading(true);
    searchTimerRef.current = setTimeout(() => {
      stocksApi.searchStocks(q, 8)
        .then((results) => {
          if (searchRequestIdRef.current === requestId) {
            setSearchResults(results);
          }
        })
        .catch(() => {
          if (searchRequestIdRef.current === requestId) {
            setSearchResults([]);
          }
        })
        .finally(() => {
          if (searchRequestIdRef.current === requestId) {
            setSearchLoading(false);
          }
        });
    }, 300);
    return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current); };
  }, [deferredSearch]);

  const handleAddToWatchlist = useCallback(async (code: string) => {
    try {
      await stocksApi.addToWatchlist([code]);
      setSearch('');
      setSearchResults([]);
      await fetchWatchlistOverview(true);
    } catch { /* ignore */ }
  }, [fetchWatchlistOverview]);

  const handleRemoveFromWatchlist = useCallback(async (code: string) => {
    try {
      await stocksApi.removeFromWatchlist(code);
      await fetchWatchlistOverview(true);
    } catch { /* ignore */ }
  }, [fetchWatchlistOverview]);

  const fetchSummaryOverview = useCallback(async (forceRefresh = false) => {
    setSummaryLoading(true);
    try {
      const nextOverview = await marketApi.getOverview(forceRefresh, {
        includeWatchlist: false,
        includeSummary: true,
      });
      setOverview((current) => mergeOverview(current, nextOverview, 'summary'));
    } catch (err) {
      if (!overviewRef.current.watchlist.length) {
        setError(err instanceof Error ? err.message : '加载实时看盘摘要失败');
      }
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchSummaryOverview();
  }, [fetchSummaryOverview]);

  const refreshOverview = useCallback(async (forceRefresh = false) => {
    setRefreshing(true);
    await Promise.allSettled([
      fetchWatchlistOverview(forceRefresh),
      fetchSummaryOverview(forceRefresh),
    ]);
    setRefreshing(false);
  }, [fetchSummaryOverview, fetchWatchlistOverview]);

  useEffect(() => {
    if (!autoRefreshInitializedRef.current) {
      autoRefreshInitializedRef.current = true;
      sessionStateRef.current = overview.sessionState;
      setAutoRefresh(overview.sessionState === 'open');
      return;
    }

    if (sessionStateRef.current !== overview.sessionState) {
      sessionStateRef.current = overview.sessionState;
      setAutoRefresh(overview.sessionState === 'open');
    }
  }, [overview]);

  useEffect(() => {
    if (!autoRefresh || !overview.refreshIntervalSeconds) return;

    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void fetchWatchlistOverview(false);
      }
    }, overview.refreshIntervalSeconds * 1000);

    return () => window.clearInterval(interval);
  }, [autoRefresh, overview.refreshIntervalSeconds, fetchWatchlistOverview]);

  const loadDailyHistory = useCallback(async (stockCode: string, days: number) => {
    const requestId = ++historyRequestIdRef.current;
    setHistoryLoading(true);
    setHistoryError(null);

    try {
      const response = await stocksApi.getHistory(stockCode, days, 'daily');
      if (requestId !== historyRequestIdRef.current) return;
      setHistoryData(response);
      setHistoryLoadedKey(`${stockCode}:${days}`);
    } catch (err) {
      if (requestId !== historyRequestIdRef.current) return;
      setHistoryError(err instanceof Error ? err.message : '加载日 K 失败');
      setHistoryData(null);
      setHistoryLoadedKey('');
    } finally {
      if (requestId === historyRequestIdRef.current) {
        setHistoryLoading(false);
      }
    }
  }, []);

  const loadIntradayData = useCallback(async (stockCode: string, interval: string, limit: number, includeTrades = true) => {
    const requestId = ++intradayRequestIdRef.current;
    setIntradayLoading(true);
    setIntradayError(null);

    try {
      const response = await stocksApi.getIntraday(stockCode, interval, limit, includeTrades);
      if (requestId !== intradayRequestIdRef.current) return;
      setIntradayData((current) => {
        if (includeTrades) {
          return response;
        }
        return {
          ...response,
          trades: current?.stockCode === response.stockCode ? current.trades : response.trades,
          tradesSource: current?.stockCode === response.stockCode ? current.tradesSource || response.tradesSource : response.tradesSource,
        };
      });
      setIntradayLoadedKey(`${stockCode}:${interval}:${limit}`);
    } catch (err) {
      if (requestId !== intradayRequestIdRef.current) return;
      setIntradayError(err instanceof Error ? err.message : '加载分时失败');
      setIntradayData(null);
      setIntradayLoadedKey('');
    } finally {
      if (requestId === intradayRequestIdRef.current) {
        setIntradayLoading(false);
      }
    }
  }, []);

  const loadSectorConstituents = useCallback(async (sectorName: string, forceRefresh = false) => {
    const requestId = ++sectorRequestIdRef.current;
    setSectorDetailLoading(true);
    setSectorDetailError(null);

    try {
      const response = await marketApi.getSectorConstituents(sectorName, forceRefresh, 10);
      if (requestId !== sectorRequestIdRef.current) return;
      setSectorDetail(response);
    } catch (err) {
      if (requestId !== sectorRequestIdRef.current) return;
      setSectorDetailError(err instanceof Error ? err.message : '加载相关股失败');
      setSectorDetail(EMPTY_SECTOR_CONSTITUENTS);
    } finally {
      if (requestId === sectorRequestIdRef.current) {
        setSectorDetailLoading(false);
      }
    }
  }, []);

  const minuteBarLimit = MINUTE_BAR_LIMITS[minuteInterval] ?? 240;

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void fetchWatchlistOverview(false);
        if (selectedStock && pricePanelViewMode === 'minute') {
          void loadIntradayData(selectedStock.stockCode, minuteInterval, minuteBarLimit, false);
        }
        if (
          !overviewRef.current.indices.length &&
          !overviewRef.current.topSectors.length &&
          !overviewRef.current.bottomSectors.length
        ) {
          void fetchSummaryOverview(false);
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [fetchSummaryOverview, fetchWatchlistOverview, loadIntradayData, minuteBarLimit, minuteInterval, pricePanelViewMode, selectedStock]);

  useEffect(() => {
    if (!selectedStock || pricePanelViewMode !== 'daily') return;
    const nextKey = `${selectedStock.stockCode}:${historyDays}`;
    if (historyLoadedKey === nextKey) return;
    void loadDailyHistory(selectedStock.stockCode, Number(historyDays));
  }, [historyDays, historyLoadedKey, loadDailyHistory, pricePanelViewMode, selectedStock]);

  useEffect(() => {
    if (!selectedStock || pricePanelViewMode !== 'minute') return;
    const nextKey = `${selectedStock.stockCode}:${minuteInterval}:${minuteBarLimit}`;
    if (intradayLoadedKey === nextKey) return;
    void loadIntradayData(selectedStock.stockCode, minuteInterval, minuteBarLimit, true);
  }, [intradayLoadedKey, loadIntradayData, minuteBarLimit, minuteInterval, pricePanelViewMode, selectedStock]);

  useEffect(() => {
    if (!selectedStock || pricePanelViewMode !== 'minute' || overview.sessionState !== 'open') return;

    const refreshSeconds = Math.max(15, overview.refreshIntervalSeconds || 15);
    const intervalId = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      void loadIntradayData(selectedStock.stockCode, minuteInterval, minuteBarLimit, false);
    }, refreshSeconds * 1000);

    return () => window.clearInterval(intervalId);
  }, [
    loadIntradayData,
    minuteBarLimit,
    minuteInterval,
    overview.refreshIntervalSeconds,
    overview.sessionState,
    pricePanelViewMode,
    selectedStock,
  ]);

  useEffect(() => {
    if (!selectedStock) {
      setHistoryFullscreen(false);
    }
  }, [selectedStock]);

  useEffect(() => {
    if (!historyFullscreen) return;

    const handleFullscreenEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setHistoryFullscreen(false);
    };

    document.addEventListener('keydown', handleFullscreenEscape, true);
    return () => document.removeEventListener('keydown', handleFullscreenEscape, true);
  }, [historyFullscreen]);

  const openDailyK = useCallback((item: Pick<MarketWatchlistItem, 'stockCode' | 'stockName'>) => {
    historyRequestIdRef.current += 1;
    intradayRequestIdRef.current += 1;
    setSelectedStock({ stockCode: item.stockCode, stockName: item.stockName });
    setPricePanelViewMode('minute');
    setHistoryError(null);
    setHistoryData(null);
    setHistoryLoadedKey('');
    setHistoryDays('60');
    setMinuteInterval('1');
    setIntradayError(null);
    setIntradayData(null);
    setIntradayLoadedKey('');
  }, []);

  const openSectorDetail = useCallback((sector: SectorSnapshot) => {
    setSelectedSector(sector);
    setSectorDrawerVisible(true);
    setResumeSectorDrawerAfterDailyK(false);
    setSectorDetail(EMPTY_SECTOR_CONSTITUENTS);
    setSectorDetailError(null);
    void loadSectorConstituents(sector.name);
  }, [loadSectorConstituents]);

  const closeSectorDetail = useCallback(() => {
    sectorRequestIdRef.current += 1;
    setSectorDrawerVisible(false);
    setResumeSectorDrawerAfterDailyK(false);
    setSelectedSector(null);
    setSectorDetail(EMPTY_SECTOR_CONSTITUENTS);
    setSectorDetailError(null);
    setSectorDetailLoading(false);
  }, []);

  const closeDailyK = useCallback(() => {
    historyRequestIdRef.current += 1;
    intradayRequestIdRef.current += 1;
    setHistoryFullscreen(false);
    resetDetail();
    setHistoryError(null);
    setHistoryLoading(false);
    setHistoryData(null);
    setHistoryLoadedKey('');
    setIntradayError(null);
    setIntradayLoading(false);
    setIntradayData(null);
    setIntradayLoadedKey('');
    if (resumeSectorDrawerAfterDailyK && selectedSector) {
      setSectorDrawerVisible(true);
      setResumeSectorDrawerAfterDailyK(false);
    }
  }, [resetDetail, resumeSectorDrawerAfterDailyK, selectedSector]);

  const openAiAnalysis = useCallback(() => {
    if (!selectedStock) return;
    const params = new URLSearchParams({
      stock: selectedStock.stockCode,
    });
    navigate(`/?${params.toString()}`);
  }, [navigate, selectedStock]);

  const handleSort = (nextKey: SortKey) => {
    if (sortKey === nextKey) {
      setSortDirection((current) => (current === 'desc' ? 'asc' : 'desc'));
      return;
    }
    setSortKey(nextKey);
    setSortDirection(nextKey === 'stockCode' || nextKey === 'stockName' || nextKey === 'source' ? 'asc' : 'desc');
  };

  const sortedWatchlist = sortWatchlist(overview.watchlist, sortKey, sortDirection, deferredSearch);
  const indexMap = new Map(overview.indices.map((item) => [item.code, item]));
  const featuredIndices = FEATURED_INDEX_CODES.map((code) => indexMap.get(code));
  const marketStats: MarketStatsSnapshot = overview.marketStats;
  const hasSummaryData =
    overview.indices.length > 0 ||
    overview.topSectors.length > 0 ||
    overview.bottomSectors.length > 0 ||
    Object.values(marketStats).some((value) => value != null);
  const historyPoints = historyData?.data || [];
  const latestHistoryPoint = historyPoints.length ? historyPoints[historyPoints.length - 1] : null;
  const minuteBars = intradayData?.bars || [];
  const latestMinuteBar = minuteBars.length ? minuteBars[minuteBars.length - 1] : null;
  const minuteStartBar = minuteBars.length ? minuteBars[0] : null;
  const minuteNetChange = latestMinuteBar && minuteStartBar ? latestMinuteBar.close - minuteStartBar.close : null;
  const minuteNetChangePercent =
    latestMinuteBar && minuteStartBar && minuteStartBar.close
      ? ((latestMinuteBar.close - minuteStartBar.close) / minuteStartBar.close) * 100
      : latestMinuteBar?.changePercent ?? null;
  const intradayTrades = intradayData?.trades || [];
  const activeChartError = pricePanelViewMode === 'minute' ? intradayError : historyError;

  return (
    <div className="min-h-screen px-4 pb-6 pt-4 md:px-6">
      {restoredNoticeVisible ? (
        <div className="mb-4 rounded-xl border border-cyan/25 bg-cyan/10 px-4 py-2 text-sm text-cyan-100">
          已恢复上次看盘详情状态。
        </div>
      ) : null}

      <header className="overflow-hidden rounded-[28px] border border-cyan/20 bg-[radial-gradient(circle_at_top_left,rgba(0,212,255,0.22),transparent_38%),linear-gradient(135deg,rgba(8,8,12,0.98),rgba(10,18,25,0.95))] p-5 shadow-[0_30px_90px_rgba(0,0,0,0.35)]">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-2xl">
            <span className="label-uppercase">REALTIME MONITOR</span>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white md:text-4xl">A股实时看盘面板</h1>
            <p className="mt-3 text-sm leading-6 text-secondary">
              聚合自选股实时行情、市场宽度、核心指数与板块冷热分布。首版仅覆盖 A 股，复用当前
              <code className="mx-1 rounded bg-white/8 px-1.5 py-0.5 text-xs text-white">STOCK_LIST</code>
              配置，不新增单独监控池。
            </p>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 lg:min-w-[420px]">
            <div className="rounded-2xl border border-white/8 bg-black/25 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.24em] text-muted">交易日</p>
              <p className="mt-1 text-lg font-semibold text-white">{overview.tradingDate || '--'}</p>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/25 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.24em] text-muted">会话状态</p>
              <div className="mt-1">
                <Badge variant={badgeVariantForSession(overview.sessionState)} size="md">
                  {sessionLabel(overview.sessionState)}
                </Badge>
              </div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/25 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.24em] text-muted">最近刷新</p>
              <p className="mt-1 text-sm font-medium text-white">{formatUpdatedAt(overview.updatedAt)}</p>
            </div>
            <div className="rounded-2xl border border-white/8 bg-black/25 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.24em] text-muted">轮询建议</p>
              <p className="mt-1 text-sm font-medium text-white">
                {overview.refreshIntervalSeconds ? `${overview.refreshIntervalSeconds}s` : '非盘中关闭'}
              </p>
            </div>
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-3 border-t border-white/8 pt-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={overview.realtimeEnabled ? 'success' : 'warning'}>
              {overview.realtimeEnabled ? '实时行情已启用' : '实时行情已关闭'}
            </Badge>
            <Badge variant="info">A股支持 {overview.supportedTotal}</Badge>
            <Badge variant="default">配置总数 {overview.watchlistTotal}</Badge>
            {watchlistLoading ? <Badge variant="info">自选股加载中</Badge> : null}
            {summaryLoading ? <Badge variant="history">总览加载中</Badge> : null}
            {overview.unsupportedCodes.length ? (
              <Badge variant="warning">已跳过 {overview.unsupportedCodes.length} 个非 A 股代码</Badge>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-2 text-sm text-secondary">
              <span>自动刷新</span>
              <button
                type="button"
                onClick={() => setAutoRefresh((current) => !current)}
                className={`relative h-7 w-12 rounded-full border transition ${
                  autoRefresh
                    ? 'border-cyan/50 bg-cyan/20'
                    : 'border-white/10 bg-white/5'
                }`}
              >
                <span
                  className={`absolute top-1 h-5 w-5 rounded-full bg-white transition ${
                    autoRefresh ? 'left-6' : 'left-1'
                  }`}
                />
              </button>
            </label>
            <Button variant="outline" isLoading={refreshing} onClick={() => void refreshOverview(true)}>
              手动刷新
            </Button>
          </div>
        </div>

        {overview.unsupportedCodes.length ? (
          <div className="mt-4 rounded-2xl border border-amber-500/20 bg-amber-500/6 px-4 py-3 text-sm text-amber-200">
            当前看盘页只展示 A 股，已跳过：
            <span className="font-medium text-white"> {overview.unsupportedCodes.join(', ')}</span>
          </div>
        ) : null}
      </header>

      {error ? (
        <Card variant="bordered" padding="lg" className="mt-4 border-red-500/30 bg-red-500/5">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <span className="label-uppercase">REQUEST FAILED</span>
              <h2 className="mt-1 text-xl font-semibold text-white">加载实时看盘失败</h2>
              <p className="mt-2 text-sm text-secondary">{error}</p>
            </div>
            <Button variant="danger" onClick={() => void refreshOverview(true)}>
              重试刷新
            </Button>
          </div>
        </Card>
      ) : null}

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_0.95fr]">
        <div className="grid gap-4">
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <IndexCard indexData={featuredIndices[0]} fallbackName="上证指数" isLoading={summaryLoading} />
            <IndexCard indexData={featuredIndices[1]} fallbackName="深证成指" isLoading={summaryLoading} />
            <IndexCard indexData={featuredIndices[2]} fallbackName="创业板指" isLoading={summaryLoading} />
            <IndexCard indexData={featuredIndices[3]} fallbackName="沪深300" isLoading={summaryLoading} />
          </section>

          <Card variant="gradient" padding="md">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <span className="label-uppercase">MARKET BREADTH</span>
                <h2 className="mt-1 text-lg font-semibold text-white">市场宽度</h2>
                {summaryLoading && !hasSummaryData ? (
                  <p className="mt-2 text-sm text-secondary">摘要数据加载中，自选股行情先行展示。</p>
                ) : null}
              </div>
              <Badge variant="info">A股全市场</Badge>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <MetricStat label="上涨家数" value={marketStats.upCount != null ? `${marketStats.upCount}` : '--'} accent="up" />
              <MetricStat label="下跌家数" value={marketStats.downCount != null ? `${marketStats.downCount}` : '--'} accent="down" />
              <MetricStat label="平盘家数" value={marketStats.flatCount != null ? `${marketStats.flatCount}` : '--'} />
              <MetricStat label="涨停" value={marketStats.limitUpCount != null ? `${marketStats.limitUpCount}` : '--'} accent="up" />
              <MetricStat label="跌停" value={marketStats.limitDownCount != null ? `${marketStats.limitDownCount}` : '--'} accent="down" />
              <MetricStat label="成交额" value={formatAmount(marketStats.totalAmount)} />
            </div>
          </Card>
        </div>

        <div className="grid gap-4">
          <Card variant="gradient" padding="md" className="h-full">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <span className="label-uppercase">SECTOR PULSE</span>
                <h2 className="mt-1 text-lg font-semibold text-white">板块冷热</h2>
              </div>
              <Badge variant="history">TOP 5</Badge>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
              <SectorList
                title="领涨板块"
                sectors={overview.topSectors}
                positive
                isLoading={summaryLoading}
                onSelect={openSectorDetail}
                selectedSectorName={selectedSector?.name}
              />
              <SectorList
                title="领跌板块"
                sectors={overview.bottomSectors}
                positive={false}
                isLoading={summaryLoading}
                onSelect={openSectorDetail}
                selectedSectorName={selectedSector?.name}
              />
            </div>
          </Card>

          <ErrorStrip errors={overview.partialErrors} />
        </div>
      </div>

      <Card variant="gradient" padding="md" className="mt-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <span className="label-uppercase">WATCHLIST MATRIX</span>
            <h2 className="mt-1 text-xl font-semibold text-white">自选股看盘表</h2>
            <p className="mt-2 text-sm text-secondary">
              默认按涨跌幅排序，失败项自动置底。支持本地搜索和列排序，点击股票可打开分时 / 日 K 走势面板。
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative">
              <input
                type="text"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                onFocus={() => setSearchFocused(true)}
                onBlur={() => setTimeout(() => setSearchFocused(false), 200)}
                placeholder="搜索添加自选股（代码/名称）"
                className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-2.5 text-sm text-white outline-none transition placeholder:text-muted focus:border-cyan/40 sm:w-72"
              />
              {searchLoading && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  <svg className="h-4 w-4 animate-spin text-muted" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                </div>
              )}
              {searchFocused && search.trim() && searchResults.length > 0 && (
                <div className="absolute top-full left-0 z-50 mt-1 w-80 rounded-xl border border-white/10 bg-[#0a0f1a]/95 shadow-xl backdrop-blur-md">
                  <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted">
                    搜索结果
                  </div>
                  {searchResults.map((item) => {
                    const isInWatchlist = overview.watchlist.some((w) => w.stockCode === item.code);
                    return (
                      <button
                        key={item.code}
                        type="button"
                        disabled={isInWatchlist}
                        onClick={() => handleAddToWatchlist(item.code)}
                        className={`flex w-full items-center justify-between px-3 py-2 text-sm transition last:rounded-b-xl ${
                          isInWatchlist
                            ? 'cursor-default text-muted'
                            : 'text-white hover:bg-white/5'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{item.code}</span>
                          <span className="text-secondary">{item.name}</span>
                          {item.industry && <span className="text-xs text-muted">{item.industry}</span>}
                        </div>
                        <span className={`text-xs ${isInWatchlist ? 'text-muted' : 'text-cyan'}`}>
                          {isInWatchlist ? '已添加' : '+ 添加'}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
              {searchFocused && search.trim() && !searchLoading && searchResults.length === 0 && (
                <div className="absolute top-full left-0 z-50 mt-1 w-80 rounded-xl border border-white/10 bg-[#0a0f1a]/95 px-3 py-4 text-center text-sm text-muted shadow-xl backdrop-blur-md">
                  未找到匹配股票
                </div>
              )}
            </div>
            <Button variant="secondary" onClick={() => navigate('/settings')}>
              去设置页
            </Button>
          </div>
        </div>

        {!watchlistLoading && overview.supportedTotal === 0 ? (
          <div className="mt-6 rounded-[24px] border border-dashed border-white/12 bg-black/20 px-6 py-10 text-center">
            <span className="label-uppercase">EMPTY WATCHLIST</span>
            <h3 className="mt-2 text-2xl font-semibold text-white">当前没有可展示的 A 股自选股</h3>
            <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-secondary">
              看盘页只读取
              <code className="mx-1 rounded bg-white/8 px-1.5 py-0.5 text-xs text-white">STOCK_LIST</code>
              中的 A 股代码。请前往设置页维护 A 股股票列表后再刷新本页。
            </p>
            <div className="mt-6">
              <Button variant="gradient" onClick={() => navigate('/settings')}>
                打开系统设置
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-5 overflow-x-auto">
            {watchlistLoading && !watchlistLoaded ? (
              <div className="mb-4 rounded-2xl border border-white/8 bg-black/20 px-4 py-3 text-sm text-secondary">
                自选股快照加载中，页面框架已先显示。慢接口会在后台继续补齐。
              </div>
            ) : null}
            <table className="min-w-[1060px] w-full border-separate border-spacing-y-2">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-[0.24em] text-muted">
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('stockCode')} className="transition hover:text-white">
                      代码 / 名称
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('currentPrice')} className="transition hover:text-white">
                      最新价
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('changePercent')} className="transition hover:text-white">
                      涨跌幅
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('change')} className="transition hover:text-white">
                      涨跌额
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('amplitude')} className="transition hover:text-white">
                      振幅
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('volumeRatio')} className="transition hover:text-white">
                      量比
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('turnoverRate')} className="transition hover:text-white">
                      换手率
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('amount')} className="transition hover:text-white">
                      成交额
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button type="button" onClick={() => handleSort('source')} className="transition hover:text-white">
                      数据源
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedWatchlist.map((item) => (
                  <tr
                    key={item.stockCode}
                    className={`rounded-2xl border ${
                      item.status === 'error'
                        ? 'border-red-500/15 bg-red-500/[0.04]'
                        : 'border-white/6 bg-black/20'
                    } cursor-pointer transition hover:-translate-y-0.5 hover:border-cyan/30 focus:outline-none focus:ring-2 focus:ring-cyan/30`}
                    role="button"
                    tabIndex={0}
                    onClick={() => openDailyK(item)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        openDailyK(item);
                      }
                    }}
                  >
                    <td className="rounded-l-2xl px-3 py-3">
                      <div className="flex items-center gap-3 cursor-pointer">
                        <div className="h-10 w-1 rounded-full bg-gradient-to-b from-cyan/80 via-cyan/30 to-transparent" />
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-white">{item.stockCode}</span>
                            <Badge variant={item.status === 'ok' ? 'success' : 'danger'}>
                              {item.status === 'ok' ? '正常' : '失败'}
                            </Badge>
                            <Badge variant="info">走势</Badge>
                          </div>
                          <p className="mt-1 text-sm text-secondary">
                            {item.stockName || item.errorMessage || '暂无股票名称'}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-sm font-semibold text-white">
                      {item.currentPrice != null ? item.currentPrice.toFixed(2) : '--'}
                    </td>
                    <td className={`px-3 py-3 text-sm font-semibold ${textClassForChange(item.changePercent)}`}>
                      {formatSigned(item.changePercent, 2, '%')}
                    </td>
                    <td className={`px-3 py-3 text-sm font-medium ${textClassForChange(item.change)}`}>
                      {formatSigned(item.change, 2)}
                    </td>
                    <td className="px-3 py-3 text-sm text-secondary">{formatPlain(item.amplitude, 2, '%')}</td>
                    <td className="px-3 py-3 text-sm text-secondary">{formatPlain(item.volumeRatio, 2)}</td>
                    <td className="px-3 py-3 text-sm text-secondary">{formatPlain(item.turnoverRate, 2, '%')}</td>
                    <td className="px-3 py-3 text-sm text-secondary">{formatAmount(item.amount)}</td>
                    <td className="rounded-r-2xl px-3 py-3">
                      <div className="flex items-center gap-2">
                        <div className="space-y-2 flex-1">
                          <Badge variant={item.source ? 'info' : 'default'}>{item.source || '--'}</Badge>
                          <div className="h-2 overflow-hidden rounded-full bg-white/8">
                            <div
                              className={`h-full rounded-full ${
                                item.status === 'error' ? 'bg-red-400/60' : 'bg-gradient-to-r from-cyan-400 to-emerald-400'
                              }`}
                              style={{ width: `${Math.max(8, Math.round((item.pricePosition ?? 0) * 100))}%` }}
                            />
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleRemoveFromWatchlist(item.stockCode);
                          }}
                          className="shrink-0 rounded-lg p-1.5 text-muted transition hover:bg-red-500/10 hover:text-red-400"
                          title="移出自选"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Drawer
        isOpen={Boolean(selectedStock)}
        onClose={closeDailyK}
        title={selectedStock ? `${selectedStock.stockCode} ${selectedStock.stockName || ''} 走势` : '走势'}
        width="max-w-5xl"
        closeOnEscape={!historyFullscreen}
      >
        <div className="space-y-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <span className="label-uppercase">INTRADAY + DAILY</span>
              <h3 className="mt-1 text-2xl font-semibold text-white">
                {selectedStock?.stockName || selectedStock?.stockCode || '--'}
              </h3>
              <p className="mt-2 text-sm text-secondary">
                {pricePanelViewMode === 'minute'
                  ? '分时模式使用免费 AkShare 分钟接口，默认展示盘中脉冲走势；逐笔成交作为补充信息尽力返回。'
                  : '日K 模式继续复用现有历史行情接口，适合回看近 30/60/120 日结构。'}
              </p>
            </div>

            <div className="flex flex-col gap-3 lg:items-end">
              <div className="inline-flex rounded-full border border-white/10 bg-black/25 p-1">
                <button
                  type="button"
                  onClick={() => setPricePanelViewMode('minute')}
                  className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                    pricePanelViewMode === 'minute'
                      ? 'bg-cyan/18 text-white shadow-[0_12px_24px_rgba(0,212,255,0.12)]'
                      : 'text-secondary hover:text-white'
                  }`}
                >
                  分时脉冲
                </button>
                <button
                  type="button"
                  onClick={() => setPricePanelViewMode('daily')}
                  className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                    pricePanelViewMode === 'daily'
                      ? 'bg-cyan/18 text-white shadow-[0_12px_24px_rgba(0,212,255,0.12)]'
                      : 'text-secondary hover:text-white'
                  }`}
                >
                  日K 回看
                </button>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <Button
                  variant="gradient"
                  onClick={openAiAnalysis}
                  disabled={!selectedStock}
                >
                  AI分析
                </Button>
                {pricePanelViewMode === 'minute' ? (
                  <Select
                    value={minuteInterval}
                    onChange={setMinuteInterval}
                    options={MINUTE_INTERVAL_OPTIONS}
                    label="分钟周期"
                    className="min-w-[160px]"
                  />
                ) : (
                  <Select
                    value={historyDays}
                    onChange={setHistoryDays}
                    options={DAILY_K_DAYS_OPTIONS}
                    label="查看区间"
                    className="min-w-[160px]"
                  />
                )}
                <Button
                  variant="outline"
                  isLoading={pricePanelViewMode === 'minute' ? intradayLoading : historyLoading}
                  onClick={() => {
                    if (!selectedStock) return;
                    if (pricePanelViewMode === 'minute') {
                      void loadIntradayData(selectedStock.stockCode, minuteInterval, minuteBarLimit);
                      return;
                    }
                    void loadDailyHistory(selectedStock.stockCode, Number(historyDays));
                  }}
                >
                  {pricePanelViewMode === 'minute' ? '刷新分时' : '刷新日K'}
                </Button>
              </div>
            </div>
          </div>

          {activeChartError ? (
            <Card variant="bordered" padding="md" className="border-red-500/30 bg-red-500/5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <span className="label-uppercase">{pricePanelViewMode === 'minute' ? 'INTRADAY FAILED' : 'KLINE FAILED'}</span>
                  <p className="mt-1 text-sm text-secondary">{activeChartError}</p>
                </div>
                <Button
                  variant="danger"
                  onClick={() => {
                    if (!selectedStock) return;
                    if (pricePanelViewMode === 'minute') {
                      void loadIntradayData(selectedStock.stockCode, minuteInterval, minuteBarLimit);
                      return;
                    }
                    void loadDailyHistory(selectedStock.stockCode, Number(historyDays));
                  }}
                >
                  重试
                </Button>
              </div>
            </Card>
          ) : null}

          <div className="grid gap-4 xl:grid-cols-[1.4fr_0.95fr]">
            <div>
              {pricePanelViewMode === 'minute' ? (
                <>
                  {intradayLoading && !minuteBars.length ? (
                    <div className="flex h-[360px] items-center justify-center rounded-2xl border border-white/8 bg-black/20 text-sm text-secondary">
                      分时数据加载中...
                    </div>
                  ) : (
                    <MinutePulseChart bars={minuteBars} onRequestFullscreen={() => setHistoryFullscreen(true)} />
                  )}
                </>
              ) : (
                <>
                  {historyLoading && !historyPoints.length ? (
                    <div className="flex h-[320px] items-center justify-center rounded-2xl border border-white/8 bg-black/20 text-sm text-secondary">
                      日K 加载中...
                    </div>
                  ) : (
                    <DailyKChart points={historyPoints} onRequestFullscreen={() => setHistoryFullscreen(true)} />
                  )}
                </>
              )}
            </div>

            {pricePanelViewMode === 'minute' ? (
              <div className="grid gap-3">
                <Card variant="gradient" padding="md">
                  <span className="label-uppercase">PULSE SNAPSHOT</span>
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">最新时间</p>
                      <p className="mt-1 text-sm font-semibold text-white">{formatDateTimeLabel(latestMinuteBar?.timestamp)}</p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">最新价</p>
                      <p className={`mt-1 text-sm font-semibold ${textClassForChange(minuteNetChange)}`}>
                        {latestMinuteBar ? latestMinuteBar.close.toFixed(2) : '--'}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">区间涨跌</p>
                      <p className={`mt-1 text-sm font-semibold ${textClassForChange(minuteNetChangePercent)}`}>
                        {formatSigned(minuteNetChangePercent, 2, '%')}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">K线根数</p>
                      <p className="mt-1 text-sm font-semibold text-white">{minuteBars.length || '--'}</p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">分钟源</p>
                      <p className="mt-1 text-sm font-semibold text-white">{intradayData?.source || '--'}</p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">逐笔源</p>
                      <p className="mt-1 text-sm font-semibold text-white">{intradayData?.tradesSource || '--'}</p>
                    </div>
                  </div>
                </Card>

                <Card variant="gradient" padding="md">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <span className="label-uppercase">RECENT PRINTS</span>
                      <h4 className="mt-1 text-lg font-semibold text-white">最近逐笔成交</h4>
                    </div>
                    <Badge variant={intradayTrades.length ? 'info' : 'warning'}>{intradayTrades.length || 0}</Badge>
                  </div>

                  {intradayTrades.length ? (
                    <div className="mt-4 space-y-2">
                      {intradayTrades.map((trade) => (
                        <div
                          key={`trade-${trade.timestamp}-${trade.price}`}
                          className="grid grid-cols-[0.92fr_0.9fr_0.7fr] items-center gap-3 rounded-xl border border-white/8 bg-black/20 px-3 py-2.5 text-sm"
                        >
                          <span className="text-secondary">{trade.timestamp}</span>
                          <span className="font-semibold text-white">{trade.price.toFixed(2)}</span>
                          <span className={`text-right ${trade.side?.includes('买') ? 'text-red-400' : trade.side?.includes('卖') ? 'text-emerald-400' : 'text-secondary'}`}>
                            {trade.side || '--'}
                            {trade.volume != null ? ` · ${trade.volume.toFixed(0)}手` : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-4 rounded-2xl border border-dashed border-white/12 bg-black/20 px-4 py-6 text-sm text-secondary">
                      逐笔成交为尽力返回项，当前免费接口未返回有效结果，但分钟K仍可正常使用。
                    </div>
                  )}
                </Card>
              </div>
            ) : (
              <div className="grid gap-3">
                <Card variant="gradient" padding="md">
                  <span className="label-uppercase">LATEST BAR</span>
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">日期</p>
                      <p className="mt-1 text-sm font-semibold text-white">{latestHistoryPoint?.date || '--'}</p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">收盘</p>
                      <p className={`mt-1 text-sm font-semibold ${textClassForChange(latestHistoryPoint ? latestHistoryPoint.close - latestHistoryPoint.open : null)}`}>
                        {latestHistoryPoint ? latestHistoryPoint.close.toFixed(2) : '--'}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">区间</p>
                      <p className="mt-1 text-sm font-semibold text-white">
                        {latestHistoryPoint ? `${latestHistoryPoint.low.toFixed(2)} / ${latestHistoryPoint.high.toFixed(2)}` : '--'}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">涨跌幅</p>
                      <p className={`mt-1 text-sm font-semibold ${textClassForChange(latestHistoryPoint?.changePercent)}`}>
                        {formatSigned(latestHistoryPoint?.changePercent, 2, '%')}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">成交量</p>
                      <p className="mt-1 text-sm font-semibold text-white">{formatAmount(latestHistoryPoint?.volume)}</p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">成交额</p>
                      <p className="mt-1 text-sm font-semibold text-white">{formatAmount(latestHistoryPoint?.amount)}</p>
                    </div>
                  </div>
                </Card>

                <Card variant="gradient" padding="md">
                  <span className="label-uppercase">DATA RANGE</span>
                  <div className="mt-3 space-y-2 text-sm text-secondary">
                    <p>当前返回 {historyPoints.length} 根日 K</p>
                    <p>
                      周期固定为日线，后端接口：
                      <code className="ml-1 rounded bg-white/8 px-1.5 py-0.5 text-xs text-white">/api/v1/stocks/{'{code}'}/history</code>
                    </p>
                    <p>切回分时模式即可查看免费分钟级走势。</p>
                  </div>
                </Card>
              </div>
            )}
          </div>

          {pricePanelViewMode === 'daily' ? (
            <div>
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <span className="label-uppercase">RECENT BARS</span>
                  <h4 className="mt-1 text-lg font-semibold text-white">最近 8 根日 K</h4>
                </div>
                {historyLoading && historyPoints.length ? <Badge variant="info">刷新中</Badge> : null}
              </div>
              <DailyKTable points={historyPoints} />
            </div>
          ) : (
            <Card variant="gradient" padding="md">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <span className="label-uppercase">FREE INTRADAY FEED</span>
                  <h4 className="mt-1 text-lg font-semibold text-white">免费分钟线试运行版</h4>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="info">AkShare</Badge>
                  <Badge variant="history">{minuteInterval} 分钟</Badge>
                  <Badge variant="default">最近 {minuteBars.length} 根</Badge>
                </div>
              </div>
              <p className="mt-3 text-sm leading-6 text-secondary">
                分时模式以免费分钟接口为主链路，优先保证单股走势可视化。逐笔成交属于补充信息，若源站波动会自动降级为空，不影响主图展示。
              </p>
            </Card>
          )}
        </div>
      </Drawer>

      <PriceChartFullscreenOverlay
        isOpen={historyFullscreen}
        onClose={() => setHistoryFullscreen(false)}
        viewMode={pricePanelViewMode}
        dailyLoading={historyLoading}
        dailyPoints={historyPoints}
        intradayLoading={intradayLoading}
        minuteBars={minuteBars}
      />

      <SectorConstituentDrawer
        isOpen={Boolean(selectedSector) && sectorDrawerVisible}
        onClose={closeSectorDetail}
        sectorName={selectedSector?.name}
        detail={sectorDetail}
        isLoading={sectorDetailLoading}
        error={sectorDetailError}
        onRefresh={() => selectedSector && void loadSectorConstituents(selectedSector.name, true)}
        onOpenStock={(item) => {
          setSectorDrawerVisible(false);
          setResumeSectorDrawerAfterDailyK(true);
          openDailyK(item);
        }}
      />
    </div>
  );
};

export default MonitorPage;
