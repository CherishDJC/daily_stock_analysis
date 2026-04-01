import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { stocksApi } from '../../api/stocks';
import type {
  StockFundFlowItem,
  StockFundFlowResponse,
  StockHistoryPoint,
  StockHistoryResponse,
  StockIntradayResponse,
  StockMetaResponse,
  StockMinuteBar,
} from '../../api/stocks';
import { Badge, Button, Card, Drawer, Select } from '../common';

type PricePanelViewMode = 'minute' | 'daily';
type HoverState = {
  index: number;
  left: number;
  top: number;
};

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

function formatSigned(value?: number | null, digits = 2, suffix = ''): string {
  if (value == null) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}${suffix}`;
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

function formatFlowAmount(value?: number | null): string {
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

function textClassForChange(value?: number | null): string {
  if (value == null) return 'text-secondary';
  if (value > 0) return 'text-red-400';
  if (value < 0) return 'text-emerald-400';
  return 'text-secondary';
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

const DailyKChart: React.FC<{ points: StockHistoryPoint[] }> = ({ points }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hoveredBar, setHoveredBar] = useState<HoverState | null>(null);

  if (!points.length) {
    return (
      <div className="flex h-[320px] items-center justify-center rounded-2xl border border-dashed border-white/12 bg-black/20 text-sm text-secondary">
        暂无日K数据
      </div>
    );
  }

  const width = 820;
  const height = 320;
  const padding = { top: 20, right: 20, bottom: 34, left: 54 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const highs = points.map((item) => item.high);
  const lows = points.map((item) => item.low);
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const priceRange = Math.max(maxPrice - minPrice, 0.01);
  const stepX = innerWidth / Math.max(points.length, 1);
  const candleWidth = Math.max(Math.min(stepX * 0.56, 10), 3);
  const labelIndexes = [0, Math.floor((points.length - 1) / 2), points.length - 1].filter(
    (value, index, array) => array.indexOf(value) === index,
  );

  const toY = (price: number) => padding.top + ((maxPrice - price) / priceRange) * innerHeight;
  const hoveredPoint = hoveredBar ? points[hoveredBar.index] : null;
  const hoveredChangePercent = hoveredBar ? resolveHistoryChangePercent(points, hoveredBar.index) : null;
  const hoveredX = hoveredBar ? padding.left + stepX * hoveredBar.index + stepX / 2 : null;

  const updateHoverState = (event: React.PointerEvent<SVGRectElement>, index: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.max(92, Math.min(event.clientX - rect.left, rect.width - 92));
    const top = Math.max(92, Math.min(event.clientY - rect.top, rect.height - 28));
    setHoveredBar({ index, left, top });
  };

  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden rounded-2xl border border-white/8 bg-black/20 p-3"
    >
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
        className="h-[320px] w-full"
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
              fontSize="11"
            >
              {formatDateLabel(points[index].date)}
            </text>
          );
        })}
      </svg>
    </div>
  );
};

const MinutePulseChart: React.FC<{ bars: StockMinuteBar[] }> = ({ bars }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hoveredBar, setHoveredBar] = useState<HoverState | null>(null);

  if (!bars.length) {
    return (
      <div className="flex h-[360px] items-center justify-center rounded-2xl border border-dashed border-white/12 bg-black/20 text-sm text-secondary">
        暂无分时数据
      </div>
    );
  }

  const width = 820;
  const height = 360;
  const padding = { top: 22, right: 20, bottom: 42, left: 54 };
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
  const labelIndexes = [0, Math.floor((bars.length - 1) / 2), bars.length - 1].filter(
    (value, index, array) => array.indexOf(value) === index,
  );

  const toX = (index: number) => padding.left + stepX * index;
  const toPriceY = (price: number) => padding.top + ((maxPrice - price) / priceRange) * priceHeight;
  const toVolumeY = (volume?: number | null) => {
    const normalized = Math.max((volume ?? 0) / volumeMax, 0);
    return volumeTop + volumeHeight - normalized * volumeHeight;
  };

  const linePath = bars.map((item, index) => `${index === 0 ? 'M' : 'L'} ${toX(index)} ${toPriceY(item.close)}`).join(' ');
  const areaPath = `${linePath} L ${toX(bars.length - 1)} ${volumeTop + volumeHeight} L ${toX(0)} ${volumeTop + volumeHeight} Z`;
  const hoveredPoint = hoveredBar ? bars[hoveredBar.index] : null;
  const hoveredChangePercent = hoveredBar ? resolveMinuteChangePercent(bars, hoveredBar.index) : null;

  const updateHoverState = (event: React.PointerEvent<SVGRectElement>, index: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.max(96, Math.min(event.clientX - rect.left, rect.width - 96));
    const top = Math.max(96, Math.min(event.clientY - rect.top, rect.height - 32));
    setHoveredBar({ index, left, top });
  };

  return (
    <div ref={containerRef} className="relative overflow-hidden rounded-2xl border border-white/8 bg-black/20 p-3">
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
        className="h-[360px] w-full"
        role="img"
        aria-label="Intraday chart"
        onPointerLeave={() => setHoveredBar(null)}
      >
        {Array.from({ length: 4 }).map((_, index) => {
          const price = maxPrice - (priceRange / 3) * index;
          const y = toPriceY(price);
          return (
            <g key={`minute-grid-${index}`}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="rgba(255,255,255,0.08)" strokeDasharray="4 4" />
              <text x={10} y={y + 4} fill="rgba(255,255,255,0.56)" fontSize="11">
                {price.toFixed(2)}
              </text>
            </g>
          );
        })}

        <path d={areaPath} fill="url(#minute-area-fill-screener)" opacity="0.92" />
        <path d={linePath} fill="none" stroke="#22d3ee" strokeWidth="2.1" strokeLinejoin="round" strokeLinecap="round" />

        {bars.map((item, index) => {
          const previousClose = index > 0 ? bars[index - 1].close : bars[0].open;
          const barColor = item.close >= previousClose ? '#f87171' : '#34d399';
          const barWidth = Math.max(2.4, stepX * 0.52);
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
            <rect x={toX(hoveredBar.index) - stepX / 2} y={padding.top} width={Math.max(stepX, 6)} height={innerHeight} fill="rgba(34,211,238,0.06)" />
            <line x1={toX(hoveredBar.index)} x2={toX(hoveredBar.index)} y1={padding.top} y2={height - padding.bottom} stroke="rgba(34,211,238,0.38)" strokeDasharray="5 5" />
            <circle cx={toX(hoveredBar.index)} cy={toPriceY(closes[hoveredBar.index])} r={3.5} fill="#22d3ee" />
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
            fontSize="11"
          >
            {formatMinuteAxisLabel(bars[index].timestamp)}
          </text>
        ))}

        <defs>
          <linearGradient id="minute-area-fill-screener" x1="0" x2="0" y1="0" y2="1">
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

const FundFlowTable: React.FC<{ rows: StockFundFlowItem[] }> = ({ rows }) => {
  if (!rows.length) {
    return (
      <div className="flex h-[180px] items-center justify-center rounded-2xl border border-dashed border-white/12 bg-black/20 text-sm text-secondary">
        暂无资金流向数据
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-white/8 bg-black/20">
      <table className="min-w-full border-separate border-spacing-0">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-[0.2em] text-muted">
            <th className="px-4 py-3">日期</th>
            <th className="px-4 py-3">收盘</th>
            <th className="px-4 py-3">涨跌幅</th>
            <th className="px-4 py-3">主力净额</th>
            <th className="px-4 py-3">主力占比</th>
            <th className="px-4 py-3">超大单</th>
            <th className="px-4 py-3">大单</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={`fund-flow-${item.date}`} className="border-t border-white/6 text-sm text-secondary">
              <td className="px-4 py-3 text-white">{item.date}</td>
              <td className="px-4 py-3">{item.close != null ? item.close.toFixed(2) : '--'}</td>
              <td className={`px-4 py-3 ${textClassForChange(item.changePercent)}`}>{formatSigned(item.changePercent, 2, '%')}</td>
              <td className={`px-4 py-3 font-medium ${textClassForChange(item.mainNetInflow)}`}>{formatFlowAmount(item.mainNetInflow)}</td>
              <td className={`px-4 py-3 ${textClassForChange(item.mainNetInflowRatio)}`}>{formatSigned(item.mainNetInflowRatio, 2, '%')}</td>
              <td className={`px-4 py-3 ${textClassForChange(item.superLargeNetInflow)}`}>{formatFlowAmount(item.superLargeNetInflow)}</td>
              <td className={`px-4 py-3 ${textClassForChange(item.largeNetInflow)}`}>{formatFlowAmount(item.largeNetInflow)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

interface StockPriceDetailDrawerProps {
  isOpen: boolean;
  stockCode?: string | null;
  stockName?: string | null;
  onClose: () => void;
  onOpenAiAnalysis?: (stockCode: string) => void;
}

export const StockPriceDetailDrawer: React.FC<StockPriceDetailDrawerProps> = ({
  isOpen,
  stockCode,
  stockName,
  onClose,
  onOpenAiAnalysis,
}) => {
  const [viewMode, setViewMode] = useState<PricePanelViewMode>('minute');
  const [historyDays, setHistoryDays] = useState('60');
  const [minuteInterval, setMinuteInterval] = useState('1');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyData, setHistoryData] = useState<StockHistoryResponse | null>(null);
  const [historyLoadedKey, setHistoryLoadedKey] = useState('');
  const [intradayLoading, setIntradayLoading] = useState(false);
  const [intradayError, setIntradayError] = useState<string | null>(null);
  const [intradayData, setIntradayData] = useState<StockIntradayResponse | null>(null);
  const [intradayLoadedKey, setIntradayLoadedKey] = useState('');
  const [fundFlowLoading, setFundFlowLoading] = useState(false);
  const [fundFlowError, setFundFlowError] = useState<string | null>(null);
  const [fundFlowData, setFundFlowData] = useState<StockFundFlowResponse | null>(null);
  const [metaLoading, setMetaLoading] = useState(false);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [metaData, setMetaData] = useState<StockMetaResponse | null>(null);
  const historyRequestIdRef = useRef(0);
  const intradayRequestIdRef = useRef(0);
  const fundFlowRequestIdRef = useRef(0);
  const metaRequestIdRef = useRef(0);

  const minuteBarLimit = MINUTE_BAR_LIMITS[minuteInterval] ?? 240;

  const loadDailyHistory = useCallback(async (nextCode: string, days: number) => {
    const requestId = ++historyRequestIdRef.current;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const response = await stocksApi.getHistory(nextCode, days, 'daily');
      if (requestId !== historyRequestIdRef.current) return;
      setHistoryData(response);
      setHistoryLoadedKey(`${nextCode}:${days}`);
    } catch (err) {
      if (requestId !== historyRequestIdRef.current) return;
      setHistoryError(err instanceof Error ? err.message : '加载日K失败');
      setHistoryData(null);
      setHistoryLoadedKey('');
    } finally {
      if (requestId === historyRequestIdRef.current) {
        setHistoryLoading(false);
      }
    }
  }, []);

  const loadIntraday = useCallback(async (nextCode: string, interval: string, limit: number) => {
    const requestId = ++intradayRequestIdRef.current;
    setIntradayLoading(true);
    setIntradayError(null);
    try {
      const response = await stocksApi.getIntraday(nextCode, interval, limit, true);
      if (requestId !== intradayRequestIdRef.current) return;
      setIntradayData(response);
      setIntradayLoadedKey(`${nextCode}:${interval}:${limit}`);
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

  const loadFundFlow = useCallback(async (nextCode: string) => {
    const requestId = ++fundFlowRequestIdRef.current;
    setFundFlowLoading(true);
    setFundFlowError(null);
    try {
      const response = await stocksApi.getFundFlow(nextCode, 10);
      if (requestId !== fundFlowRequestIdRef.current) return;
      setFundFlowData(response);
    } catch (err) {
      if (requestId !== fundFlowRequestIdRef.current) return;
      setFundFlowError(err instanceof Error ? err.message : '加载资金流向失败');
      setFundFlowData(null);
    } finally {
      if (requestId === fundFlowRequestIdRef.current) {
        setFundFlowLoading(false);
      }
    }
  }, []);

  const loadMeta = useCallback(async (nextCode: string) => {
    const requestId = ++metaRequestIdRef.current;
    setMetaLoading(true);
    setMetaError(null);
    try {
      const response = await stocksApi.getMeta(nextCode);
      if (requestId !== metaRequestIdRef.current) return;
      setMetaData(response);
    } catch (err) {
      if (requestId !== metaRequestIdRef.current) return;
      setMetaError(err instanceof Error ? err.message : '加载基础信息失败');
      setMetaData(null);
    } finally {
      if (requestId === metaRequestIdRef.current) {
        setMetaLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!isOpen || !stockCode) return;
    setViewMode('minute');
    setHistoryDays('60');
    setMinuteInterval('1');
    setHistoryData(null);
    setHistoryLoadedKey('');
    setIntradayData(null);
    setIntradayLoadedKey('');
    setMetaData(null);
    setMetaError(null);
    setHistoryError(null);
    setIntradayError(null);
    void loadIntraday(stockCode, '1', MINUTE_BAR_LIMITS['1']);
    void loadFundFlow(stockCode);
    void loadMeta(stockCode);
  }, [isOpen, stockCode, loadFundFlow, loadIntraday, loadMeta]);

  useEffect(() => {
    if (!isOpen || !stockCode || viewMode !== 'daily') return;
    const nextKey = `${stockCode}:${historyDays}`;
    if (historyLoadedKey === nextKey) return;
    void loadDailyHistory(stockCode, Number(historyDays));
  }, [historyDays, historyLoadedKey, isOpen, loadDailyHistory, stockCode, viewMode]);

  useEffect(() => {
    if (!isOpen || !stockCode || viewMode !== 'minute') return;
    const nextKey = `${stockCode}:${minuteInterval}:${minuteBarLimit}`;
    if (intradayLoadedKey === nextKey) return;
    void loadIntraday(stockCode, minuteInterval, minuteBarLimit);
  }, [intradayLoadedKey, isOpen, loadIntraday, minuteBarLimit, minuteInterval, stockCode, viewMode]);

  const historyPoints = historyData?.data || [];
  const minuteBars = intradayData?.bars || [];
  const trades = intradayData?.trades || [];
  const fundRows = fundFlowData?.data || [];
  const latestFund = fundRows[0];
  const rolling3d = fundRows.slice(0, 3).reduce((sum, item) => sum + (item.mainNetInflow || 0), 0);
  const rolling5d = fundRows.slice(0, 5).reduce((sum, item) => sum + (item.mainNetInflow || 0), 0);

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={stockCode ? `${stockCode} ${stockName || ''} 详情` : '个股详情'}
      width="max-w-5xl"
    >
      <div className="space-y-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <span className="label-uppercase">PRICE DETAIL</span>
            <h3 className="mt-1 text-2xl font-semibold text-white">{stockName || stockCode || '--'}</h3>
            <p className="mt-2 text-sm text-secondary">
              查看推荐股票的分钟线、日线结构和最近主力资金流向，便于快速二次判断。
            </p>
          </div>

          <div className="flex flex-col gap-3 lg:items-end">
            <div className="inline-flex rounded-full border border-white/10 bg-black/25 p-1">
              <button
                type="button"
                onClick={() => setViewMode('minute')}
                className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                  viewMode === 'minute'
                    ? 'bg-cyan/18 text-white shadow-[0_12px_24px_rgba(0,212,255,0.12)]'
                    : 'text-secondary hover:text-white'
                }`}
              >
                分钟线
              </button>
              <button
                type="button"
                onClick={() => setViewMode('daily')}
                className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                  viewMode === 'daily'
                    ? 'bg-cyan/18 text-white shadow-[0_12px_24px_rgba(0,212,255,0.12)]'
                    : 'text-secondary hover:text-white'
                }`}
              >
                日线
              </button>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              {viewMode === 'minute' ? (
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
                isLoading={viewMode === 'minute' ? intradayLoading : historyLoading}
                onClick={() => {
                  if (!stockCode) return;
                  if (viewMode === 'minute') {
                    void loadIntraday(stockCode, minuteInterval, minuteBarLimit);
                    return;
                  }
                  void loadDailyHistory(stockCode, Number(historyDays));
                }}
              >
                {viewMode === 'minute' ? '刷新分钟线' : '刷新日线'}
              </Button>
              {onOpenAiAnalysis && stockCode ? (
                <Button variant="gradient" onClick={() => onOpenAiAnalysis(stockCode)}>
                  AI分析
                </Button>
              ) : null}
            </div>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.38fr_0.92fr]">
          <div>
            {viewMode === 'minute' ? (
              intradayLoading && !minuteBars.length ? (
                <div className="flex h-[360px] items-center justify-center rounded-2xl border border-white/8 bg-black/20 text-sm text-secondary">
                  分钟线加载中...
                </div>
              ) : (
                <MinutePulseChart bars={minuteBars} />
              )
            ) : historyLoading && !historyPoints.length ? (
              <div className="flex h-[320px] items-center justify-center rounded-2xl border border-white/8 bg-black/20 text-sm text-secondary">
                日线加载中...
              </div>
            ) : (
              <DailyKChart points={historyPoints} />
            )}
          </div>

          <div className="grid gap-3">
            <Card variant="gradient" padding="md">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <span className="label-uppercase">STOCK PROFILE</span>
                  <h4 className="mt-1 text-lg font-semibold text-white">基础信息</h4>
                </div>
                <Badge variant={metaData?.source ? 'info' : metaLoading ? 'info' : 'warning'}>
                  {metaData?.source || (metaLoading ? '加载中' : '暂无')}
                </Badge>
              </div>

              {metaError ? <p className="mt-3 text-sm text-red-400">{metaError}</p> : null}

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">行业</p>
                  <p className="mt-1 text-sm font-semibold text-white">{metaData?.industry || '--'}</p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">市场 / 地区</p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {[metaData?.market, metaData?.area].filter(Boolean).join(' / ') || '--'}
                  </p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">上市日期</p>
                  <p className="mt-1 text-sm font-semibold text-white">{metaData?.listDate || '--'}</p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">PE / PB</p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {metaData?.peRatio != null ? metaData.peRatio.toFixed(2) : '--'} / {metaData?.pbRatio != null ? metaData.pbRatio.toFixed(2) : '--'}
                  </p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">总市值</p>
                  <p className="mt-1 text-sm font-semibold text-white">{formatAmount(metaData?.totalMarketValue)}</p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">流通市值</p>
                  <p className="mt-1 text-sm font-semibold text-white">{formatAmount(metaData?.circulatingMarketValue)}</p>
                </div>
              </div>

              {metaData?.belongBoards?.length ? (
                <div className="mt-4">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">所属板块</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {metaData.belongBoards.map((board) => (
                      <Badge key={board} variant="default">{board}</Badge>
                    ))}
                  </div>
                </div>
              ) : null}

              {metaData?.mainBusiness ? (
                <div className="mt-4 rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">主营业务</p>
                  <p className="mt-1 text-sm leading-6 text-secondary">{metaData.mainBusiness}</p>
                </div>
              ) : null}
            </Card>

            {viewMode === 'minute' ? (
              <Card variant="gradient" padding="md">
                <span className="label-uppercase">RECENT PRINTS</span>
                <h4 className="mt-1 text-lg font-semibold text-white">最近逐笔成交</h4>
                {intradayError ? <p className="mt-2 text-sm text-red-400">{intradayError}</p> : null}
                {trades.length ? (
                  <div className="mt-4 space-y-2">
                    {trades.map((trade) => (
                      <div key={`${trade.timestamp}-${trade.price}`} className="grid grid-cols-[0.92fr_0.9fr_0.7fr] items-center gap-3 rounded-xl border border-white/8 bg-black/20 px-3 py-2.5 text-sm">
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
                    暂无逐笔成交，分钟线仍可正常查看。
                  </div>
                )}
              </Card>
            ) : (
              <Card variant="gradient" padding="md">
                <span className="label-uppercase">LATEST BAR</span>
                <h4 className="mt-1 text-lg font-semibold text-white">最新日线</h4>
                {historyError ? <p className="mt-2 text-sm text-red-400">{historyError}</p> : null}
                {historyPoints.length ? (
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">日期</p>
                      <p className="mt-1 text-sm font-semibold text-white">{historyPoints[historyPoints.length - 1].date}</p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">收盘</p>
                      <p className="mt-1 text-sm font-semibold text-white">{historyPoints[historyPoints.length - 1].close.toFixed(2)}</p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">涨跌幅</p>
                      <p className={`mt-1 text-sm font-semibold ${textClassForChange(historyPoints[historyPoints.length - 1].changePercent)}`}>
                        {formatSigned(historyPoints[historyPoints.length - 1].changePercent, 2, '%')}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.2em] text-muted">成交额</p>
                      <p className="mt-1 text-sm font-semibold text-white">{formatAmount(historyPoints[historyPoints.length - 1].amount)}</p>
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 rounded-2xl border border-dashed border-white/12 bg-black/20 px-4 py-6 text-sm text-secondary">
                    暂无日线数据。
                  </div>
                )}
              </Card>
            )}

            <Card variant="gradient" padding="md">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <span className="label-uppercase">MAIN FUND FLOW</span>
                  <h4 className="mt-1 text-lg font-semibold text-white">主力资金流向</h4>
                </div>
                <Badge variant={fundRows.length ? 'info' : 'warning'}>
                  {fundFlowData?.source || (fundFlowLoading ? '加载中' : '暂无')}
                </Badge>
              </div>

              {fundFlowError ? <p className="mt-3 text-sm text-red-400">{fundFlowError}</p> : null}

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">最新日期</p>
                  <p className="mt-1 text-sm font-semibold text-white">{latestFund?.date || '--'}</p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">最新主力净额</p>
                  <p className={`mt-1 text-sm font-semibold ${textClassForChange(latestFund?.mainNetInflow)}`}>
                    {formatFlowAmount(latestFund?.mainNetInflow)}
                  </p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">最新主力占比</p>
                  <p className={`mt-1 text-sm font-semibold ${textClassForChange(latestFund?.mainNetInflowRatio)}`}>
                    {formatSigned(latestFund?.mainNetInflowRatio, 2, '%')}
                  </p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted">3日 / 5日累计</p>
                  <p className={`mt-1 text-sm font-semibold ${textClassForChange(rolling3d || rolling5d)}`}>
                    {formatFlowAmount(rolling3d)} / {formatFlowAmount(rolling5d)}
                  </p>
                </div>
              </div>
            </Card>
          </div>
        </div>

        <div className="space-y-4">
          {viewMode === 'daily' ? (
            <Card variant="gradient" padding="md">
              <span className="label-uppercase">RECENT DAILY BARS</span>
              <h4 className="mt-1 text-lg font-semibold text-white">最近 8 根日线</h4>
              <div className="mt-4">
                <DailyKTable points={historyPoints} />
              </div>
            </Card>
          ) : null}

          <Card variant="gradient" padding="md">
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="label-uppercase">FUND FLOW DETAILS</span>
                <h4 className="mt-1 text-lg font-semibold text-white">最近资金流明细</h4>
              </div>
              {fundFlowLoading ? <Badge variant="info">加载中</Badge> : null}
            </div>
            <div className="mt-4">
              <FundFlowTable rows={fundRows} />
            </div>
          </Card>
        </div>
      </div>
    </Drawer>
  );
};
