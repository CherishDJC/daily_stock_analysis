import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { screenerApi } from '../api/screener';
import type {
  ScreenerProgressStep,
  ScreenerDashboard,
  ScreenerResult,
  ScreenerHistoryItem,
} from '../api/screener';
import { agentApi } from '../api/agent';
import { StockPriceDetailDrawer } from '../components/stocks/StockPriceDetailDrawer';
import { useScreenerStore } from '../stores';

// Quick screening presets
const QUICK_PRESETS = [
  { label: '多头趋势回踩', query: '帮我找 MA5>MA10>MA20 多头排列、股价缩量回踩 MA10 支撑的股票' },
  { label: '放量突破新高', query: '帮我找放量突破20日新高、量比>1.5 的股票' },
  { label: '筹码集中低位', query: '帮我找筹码集中度高(90%集中度<15%)、股价在平均成本附近、PE合理的股票' },
  { label: '强势板块龙头', query: '帮我找今日强势板块中的龙头股，趋势向上不追高' },
  { label: '低估蓝筹', query: '帮我找PE<20、市值>500亿、趋势稳定的低估值蓝筹股' },
  { label: '缩量蓄势', query: '帮我找近期缩量整理、均线粘合即将方向选择的股票' },
];

/** Extract markdown report (before JSON block) and strip the JSON block from content */
function extractReport(content: string): string {
  if (!content) return '';
  // Remove the JSON code block (```json ... ```) from the end
  return content.replace(/```json\s*\n[\s\S]*?\n```/g, '').trim();
}

/** Render a single progress step with appropriate styling */
const StepItem: React.FC<{ step: ScreenerProgressStep }> = ({ step }) => {
  if (step.type === 'thinking') {
    return (
      <div className="flex items-center gap-2 text-xs py-1 text-blue-400">
        <svg className="w-3 h-3 flex-shrink-0 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        <span>{step.message || 'AI 思考中...'}</span>
      </div>
    );
  }
  if (step.type === 'tool_start') {
    return (
      <div className="flex items-center gap-2 text-xs py-0.5 text-secondary">
        <div className="w-3 h-3 flex-shrink-0 flex items-center justify-center">
          <div className="w-2 h-2 rounded-full border border-cyan/50 border-t-cyan animate-spin" />
        </div>
        <span>{step.display_name || step.tool}...</span>
      </div>
    );
  }
  if (step.type === 'tool_done') {
    return (
      <div className={`flex items-center gap-2 text-xs py-0.5 ${step.success ? 'text-green-400/80' : 'text-red-400/80'}`}>
        <span className="w-3 text-center flex-shrink-0">{step.success ? '✓' : '✗'}</span>
        <span className="flex-1">{step.display_name || step.tool}</span>
        <span className="text-muted tabular-nums">{step.duration}s</span>
      </div>
    );
  }
  if (step.type === 'generating') {
    return (
      <div className="flex items-center gap-2 text-xs py-1 text-purple-400">
        <svg className="w-3 h-3 flex-shrink-0 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
        </svg>
        <span>{step.message || '正在生成选股报告...'}</span>
      </div>
    );
  }
  return null;
};

const ScreenerPage: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [strategies, setStrategies] = useState<{ id: string; name: string }[]>([]);
  const [progressSteps, setProgressSteps] = useState<ScreenerProgressStep[]>([]);
  const progressEndRef = useRef<HTMLDivElement>(null);
  const {
    input,
    selectedStrategy,
    dashboard,
    report,
    error,
    selectedStock,
    setInput,
    setSelectedStrategy,
    setDashboard,
    setReport,
    setError,
    setSelectedStock,
    resetResult,
  } = useScreenerStore();

  // History state
  const [showHistory, setShowHistory] = useState(false);
  const [historyList, setHistoryList] = useState<ScreenerHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [restoredNoticeVisible, setRestoredNoticeVisible] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await screenerApi.getHistory(30);
      setHistoryList(res.records);
    } catch { /* ignore */ } finally {
      setHistoryLoading(false);
    }
  }, []);

  // Auto-scroll progress to bottom
  useEffect(() => {
    if (progressEndRef.current) {
      progressEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [progressSteps]);

  useEffect(() => {
    agentApi.getStrategies().then((res) => {
      setStrategies(res.strategies.map((s) => ({ id: s.id, name: s.name })));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (showHistory) loadHistory();
  }, [showHistory, loadHistory]);

  useEffect(() => {
    if (!dashboard && !report && !input) return;
    setRestoredNoticeVisible(true);
    const timer = window.setTimeout(() => {
      setRestoredNoticeVisible(false);
    }, 2800);
    return () => window.clearTimeout(timer);
  }, []);

  const getCurrentStage = (steps: ScreenerProgressStep[]): string => {
    if (steps.length === 0) return '正在连接...';
    const last = steps[steps.length - 1];
    if (last.type === 'thinking') return last.message || 'AI 正在思考...';
    if (last.type === 'tool_start') return `${last.display_name || last.tool}...`;
    if (last.type === 'tool_done') return `${last.display_name || last.tool} 完成`;
    if (last.type === 'generating') return last.message || '正在生成选股报告...';
    return '处理中...';
  };

  const getStepCount = (steps: ScreenerProgressStep[]) => {
    const done = steps.filter((s) => s.type === 'tool_done').length;
    const started = steps.filter((s) => s.type === 'tool_start').length;
    return { done, started, inFlight: started - done };
  };

  const handleScreen = async (overrideQuery?: string) => {
    const query = overrideQuery || input.trim();
    if (!query || loading) return;

    setLoading(true);
    setError(null);
    setProgressSteps([]);
    resetResult();
    setInput(query === overrideQuery ? '' : input);

    const skills = selectedStrategy ? [selectedStrategy] : undefined;

    try {
      const response = await screenerApi.streamScreener({ query, skills });

      if (!response.body) throw new Error('No response body');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let finalContent: string | null = null;
      let finalDashboard: ScreenerDashboard | null = null;
      let finalTotalTokens = 0;
      let finalProvider: string | null = null;
      let finalError: string | null = null;
      let finalSuccess = false;
      const currentSteps: ScreenerProgressStep[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'heartbeat') continue; // ignore keepalive
            if (event.type === 'done') {
              finalSuccess = event.success !== false;
              finalContent = event.content ?? '';
              finalTotalTokens = typeof event.total_tokens === 'number' ? event.total_tokens : 0;
              finalProvider = typeof event.provider === 'string' ? event.provider : null;
              finalError = typeof event.error === 'string' && event.error ? event.error : null;
              if (event.dashboard) {
                finalDashboard = event.dashboard as ScreenerDashboard;
              }
            } else if (event.type === 'error') {
              throw new Error(event.message || '选股出错');
            } else {
              currentSteps.push(event);
              setProgressSteps((prev) => [...prev, event]);
            }
          } catch (parseErr: unknown) {
            if ((parseErr as Error).message && !(parseErr as Error).message.includes('JSON')) throw parseErr;
          }
        }
      }

      // Try to parse dashboard from content if not already provided
      if (finalContent && !finalDashboard) {
        try {
          const jsonMatch = finalContent.match(/```json\s*\n?([\s\S]*?)\n?```/);
          if (jsonMatch) {
            finalDashboard = JSON.parse(jsonMatch[1]);
          } else {
            const braceStart = finalContent.indexOf('{');
            const braceEnd = finalContent.lastIndexOf('}');
            if (braceStart >= 0 && braceEnd > braceStart) {
              finalDashboard = JSON.parse(finalContent.substring(braceStart, braceEnd + 1));
            }
          }
        } catch {
          // If dashboard parse fails, just show the raw report
        }
      }

      if (finalDashboard) setDashboard(finalDashboard);
      // Strip JSON block, show only the markdown report
      const finalReport = finalContent ? extractReport(finalContent) : '';
      if (finalReport) setReport(finalReport);
      if (finalError) setError(finalError);

      const finalResultCount = finalDashboard?.results?.length ?? 0;
      const finalStatus = finalError
        ? (finalDashboard || finalReport ? 'partial' : 'failed')
        : finalResultCount > 0
          ? 'success'
          : 'empty';

      // Auto-save result to history
      if (finalContent || finalDashboard || finalError) {
        try {
          await screenerApi.save({
            query,
            dashboard: finalDashboard || undefined,
            results: finalDashboard?.results,
            report_markdown: finalReport || undefined,
            status: finalStatus,
            provider: finalProvider || undefined,
            error_message: finalError || undefined,
            result_count: finalResultCount,
            strategy_summary: finalDashboard?.strategy_summary,
            risk_warning: finalDashboard?.risk_warning || finalError || undefined,
            total_steps: currentSteps.filter((s) => s.type === 'tool_done').length,
            total_tokens: finalTotalTokens,
          });
          if (showHistory) loadHistory();
        } catch { /* ignore save failure */ }
      }

      if (!finalSuccess && !finalDashboard && !finalReport) {
        throw new Error(finalError || '选股分析失败');
      }
    } catch (err: unknown) {
      const msg = (err as Error).message || '未知错误';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadHistory = async (record: ScreenerHistoryItem) => {
    try {
      const detail = await screenerApi.getDetail(record.id);
      if (detail.dashboard) {
        setDashboard(detail.dashboard);
      } else if (Array.isArray(detail.results)) {
        setDashboard({
          query: detail.query,
          market_overview: { hot_sectors: [], cold_sectors: [], market_style: '' },
          results: detail.results as ScreenerResult[],
          strategy_summary: detail.strategy_summary || '',
          risk_warning: detail.risk_warning || '',
          action_plan: '',
        });
      } else {
        setDashboard(null);
      }
      setReport(detail.report_markdown || '');
      setError(detail.error_message || null);
      setProgressSteps([]);
      setShowHistory(false);
    } catch { /* ignore */ }
  };

  const handleDeleteHistory = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await screenerApi.deleteRecord(id);
      setHistoryList((prev) => prev.filter((r) => r.id !== id));
    } catch { /* ignore */ }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleScreen();
    }
  };

  const getSignalBadge = (signal: string, score: number) => {
    if (score >= 70 || signal.includes('买入')) return { bg: 'bg-green-500/20', text: 'text-green-400', border: 'border-green-500/30', label: signal };
    if (score >= 50 || signal.includes('持有')) return { bg: 'bg-yellow-500/20', text: 'text-yellow-400', border: 'border-yellow-500/30', label: signal };
    return { bg: 'bg-red-500/20', text: 'text-red-400', border: 'border-red-500/30', label: signal };
  };

  const { done: doneCount, inFlight } = getStepCount(progressSteps);

  const openStockDetail = useCallback((code: string, name?: string | null) => {
    setSelectedStock({ code, name: name || code });
  }, []);

  const openAiAnalysis = useCallback((code: string) => {
    const params = new URLSearchParams({ stock: code });
    navigate(`/?${params.toString()}`);
  }, [navigate]);

  return (
    <div className="min-h-screen flex max-w-7xl mx-auto w-full p-4 md:p-6 gap-4">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="mb-4 flex-shrink-0 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <svg className="w-6 h-6 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              智能选股
            </h1>
          </div>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-secondary hover:text-white hover:border-cyan/40 transition-all flex items-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            历史
          </button>
        </header>

        {restoredNoticeVisible ? (
          <div className="glass-card p-3 mb-3 border-cyan/25 bg-cyan/10 flex-shrink-0">
            <p className="text-sm text-cyan-100">已恢复上次选股状态。</p>
          </div>
        ) : null}

        {/* Input area */}
        <div className="glass-card p-4 mb-3 flex-shrink-0">
          {/* Quick presets */}
          <div className="flex flex-wrap gap-2 mb-3">
            {QUICK_PRESETS.map((preset, i) => (
              <button
                key={i}
                onClick={() => handleScreen(preset.query)}
                disabled={loading}
                className="px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-xs text-secondary hover:text-white hover:border-cyan/40 hover:bg-cyan/5 transition-all disabled:opacity-40"
              >
                {preset.label}
              </button>
            ))}
          </div>

          {/* Strategy selector */}
          {strategies.length > 0 && (
            <div className="flex flex-wrap gap-3 items-center mb-3">
              <span className="text-xs text-muted font-medium uppercase tracking-wider">策略</span>
              <label className="flex items-center gap-1.5 text-sm cursor-pointer">
                <input
                  type="radio"
                  name="screener-strategy"
                  value=""
                  checked={selectedStrategy === ''}
                  onChange={() => setSelectedStrategy('')}
                  className="w-3.5 h-3.5 accent-cyan"
                />
                <span className={selectedStrategy === '' ? 'text-white font-medium' : 'text-secondary'}>通用</span>
              </label>
              {strategies.slice(0, 5).map((s) => (
                <label key={s.id} className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="screener-strategy"
                    value={s.id}
                    checked={selectedStrategy === s.id}
                    onChange={() => setSelectedStrategy(s.id)}
                    className="w-3.5 h-3.5 accent-cyan"
                  />
                  <span className={selectedStrategy === s.id ? 'text-white font-medium text-sm' : 'text-secondary text-sm'}>
                    {s.name}
                  </span>
                </label>
              ))}
            </div>
          )}

          {/* Text input */}
          <div className="flex gap-3 items-end">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="描述选股条件，如：帮我找多头排列、缩量回踩MA10、PE<30的股票"
              disabled={loading}
              rows={2}
              className="input-terminal flex-1 min-h-[60px] max-h-[160px] py-2.5 resize-none"
              style={{ height: 'auto' }}
              onInput={(e) => {
                const t = e.target as HTMLTextAreaElement;
                t.style.height = 'auto';
                t.style.height = `${Math.min(t.scrollHeight, 160)}px`;
              }}
            />
            <button
              onClick={() => handleScreen()}
              disabled={(!input.trim() && !loading) || loading}
              className="btn-primary h-[52px] px-6 flex-shrink-0 flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  筛选中
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                  开始筛选
                </>
              )}
            </button>
          </div>
        </div>

        {/* Progress area — scrollable live log */}
        {(loading || progressSteps.length > 0) && (
          <div className="glass-card mb-3 flex-shrink-0 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-white/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                {loading && (
                  <div className="relative w-3.5 h-3.5 flex-shrink-0">
                    <div className="absolute inset-0 rounded-full border-2 border-cyan/20" />
                    <div className="absolute inset-0 rounded-full border-2 border-cyan border-t-transparent animate-spin" />
                  </div>
                )}
                <span className="text-xs text-secondary font-medium">
                  {loading ? getCurrentStage(progressSteps) : `分析完成 · ${doneCount} 个步骤`}
                </span>
              </div>
              {loading && (
                <span className="text-xs text-muted tabular-nums">
                  {doneCount > 0 && `已完成 ${doneCount} 步`}
                  {inFlight > 0 && ` · 进行中 ${inFlight}`}
                </span>
              )}
            </div>
            <div className="px-4 py-2 max-h-48 overflow-y-auto scrollbar-thin">
              {progressSteps.map((step, idx) => (
                <StepItem key={idx} step={step} />
              ))}
              <div ref={progressEndRef} />
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="glass-card p-4 mb-3 border-red-500/30 bg-red-500/5">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}

        {/* Results table */}
        {dashboard?.results && dashboard.results.length > 0 && (
          <div className="glass-card mb-3 overflow-hidden flex-shrink-0">
            <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
              <h2 className="text-sm font-medium text-white">
                筛选结果
                <span className="ml-2 text-xs text-muted">({dashboard.results.length} 只)</span>
              </h2>
              {dashboard.strategy_summary && (
                <span className="text-xs text-muted">{dashboard.strategy_summary.slice(0, 80)}</span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5 text-muted">
                    <th className="text-left px-4 py-2.5 font-medium">股票</th>
                    <th className="text-right px-3 py-2.5 font-medium">现价</th>
                    <th className="text-right px-3 py-2.5 font-medium">涨跌幅</th>
                    <th className="text-center px-3 py-2.5 font-medium">信号</th>
                    <th className="text-left px-3 py-2.5 font-medium">板块</th>
                    <th className="text-right px-3 py-2.5 font-medium">PE</th>
                    <th className="text-left px-4 py-2.5 font-medium">推荐理由</th>
                    <th className="text-center px-3 py-2.5 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {dashboard.results.map((stock: ScreenerResult, idx: number) => {
                    const badge = getSignalBadge(stock.signal || '观望', stock.signal_score || 0);
                    return (
                      <tr
                        key={stock.code || idx}
                        className="border-b border-white/5 hover:bg-white/5 transition-colors cursor-pointer"
                        role="button"
                        tabIndex={0}
                        onClick={() => openStockDetail(stock.code, stock.name)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            openStockDetail(stock.code, stock.name);
                          }
                        }}
                      >
                        <td className="px-4 py-2.5">
                          <div className="text-white font-medium">{stock.name || stock.code}</div>
                          <div className="text-xs text-muted">{stock.code}</div>
                        </td>
                        <td className="text-right px-3 py-2.5 text-white">{stock.price?.toFixed(2) ?? '-'}</td>
                        <td className={`text-right px-3 py-2.5 ${(stock.change_pct || 0) >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                          {stock.change_pct != null ? `${stock.change_pct > 0 ? '+' : ''}${stock.change_pct.toFixed(2)}%` : '-'}
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          <span className={`inline-flex px-2 py-0.5 rounded-full text-xs ${badge.bg} ${badge.text} border ${badge.border}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-secondary text-xs">{stock.sector || '-'}</td>
                        <td className="text-right px-3 py-2.5 text-secondary">{stock.pe_ratio?.toFixed(1) ?? '-'}</td>
                        <td className="px-4 py-2.5 text-secondary text-xs max-w-[200px] truncate">{stock.reason || '-'}</td>
                        <td className="px-3 py-2.5 text-center">
                          <div className="flex items-center justify-center gap-2">
                            <button
                              onClick={(event) => {
                                event.stopPropagation();
                                openStockDetail(stock.code, stock.name);
                              }}
                              className="px-2.5 py-1 rounded-lg bg-cyan/10 border border-cyan/20 text-cyan text-xs hover:bg-cyan/20 transition-colors"
                            >
                              详情
                            </button>
                            <button
                              onClick={(event) => {
                                event.stopPropagation();
                                openAiAnalysis(stock.code);
                              }}
                              className="px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-secondary text-xs hover:text-white hover:border-cyan/30 transition-colors"
                            >
                              AI分析
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {dashboard.risk_warning && (
              <div className="px-4 py-2.5 border-t border-white/5 text-xs text-muted">
                ⚠️ {dashboard.risk_warning}
              </div>
            )}
          </div>
        )}

        {/* Market overview */}
        {dashboard?.market_overview && (
          <div className="glass-card p-4 mb-3 flex-shrink-0">
            <h2 className="text-sm font-medium text-white mb-2">市场概览</h2>
            <div className="flex flex-wrap gap-4 text-xs">
              {dashboard.market_overview.hot_sectors?.length > 0 && (
                <div>
                  <span className="text-muted">热门板块：</span>
                  <span className="text-red-400">{dashboard.market_overview.hot_sectors.join('、')}</span>
                </div>
              )}
              {dashboard.market_overview.cold_sectors?.length > 0 && (
                <div>
                  <span className="text-muted">冷门板块：</span>
                  <span className="text-green-400">{dashboard.market_overview.cold_sectors.join('、')}</span>
                </div>
              )}
              {dashboard.market_overview.market_style && (
                <div>
                  <span className="text-muted">市场风格：</span>
                  <span className="text-white">{dashboard.market_overview.market_style}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* AI Report — render markdown only, JSON block stripped */}
        {report && (
          <div className="glass-card p-4 mb-3 flex-shrink-0">
            <h2 className="text-sm font-medium text-white mb-3">AI 选股报告</h2>
            <div className="prose prose-invert prose-sm max-w-none
              prose-headings:text-white prose-headings:font-semibold prose-headings:mt-4 prose-headings:mb-2
              prose-h1:text-lg prose-h2:text-base prose-h3:text-sm
              prose-p:leading-relaxed prose-p:mb-2 prose-p:last:mb-0
              prose-strong:text-white prose-strong:font-semibold
              prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5
              prose-code:text-cyan prose-code:bg-white/5 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs
              prose-pre:bg-black/30 prose-pre:border prose-pre:border-white/10 prose-pre:rounded-lg prose-pre:p-3
              prose-table:w-full prose-table:text-sm
              prose-th:text-white prose-th:font-medium prose-th:border-white/20 prose-th:px-3 prose-th:py-1.5 prose-th:bg-white/5
              prose-td:border-white/10 prose-td:px-3 prose-td:py-1.5
              prose-hr:border-white/10 prose-hr:my-3
              prose-a:text-cyan prose-a:no-underline hover:prose-a:underline
              prose-blockquote:border-cyan/30 prose-blockquote:text-secondary
            ">
              <Markdown remarkPlugins={[remarkGfm]}>{report}</Markdown>
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && !dashboard && !report && !error && progressSteps.length === 0 && (
          <div className="flex-1 flex flex-col items-center justify-center text-center">
            <div className="w-16 h-16 mb-4 rounded-2xl bg-white/5 flex items-center justify-center">
              <svg className="w-8 h-8 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
            <h3 className="text-lg font-medium text-white mb-2">AI 智能选股</h3>
            <p className="text-sm text-secondary max-w-sm mb-2">
              输入选股条件或点击上方快捷标签，AI 将自动扫描市场并筛选出符合条件的股票。
            </p>
            <p className="text-xs text-muted">
              支持：多头趋势 · 放量突破 · 筹码集中 · 低估蓝筹 · 板块龙头 等策略
            </p>
          </div>
        )}
      </div>

      {/* History sidebar */}
      {showHistory && (
        <div className="w-72 flex-shrink-0 glass-card p-0 flex flex-col max-h-screen overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
            <h3 className="text-sm font-medium text-white">选股历史</h3>
            <button
              onClick={() => setShowHistory(false)}
              className="text-muted hover:text-white transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {historyLoading ? (
              <div className="p-4 text-center text-xs text-muted">加载中...</div>
            ) : historyList.length === 0 ? (
              <div className="p-4 text-center text-xs text-muted">暂无历史记录</div>
            ) : (
              historyList.map((record) => (
                <div
                  key={record.id}
                  onClick={() => handleLoadHistory(record)}
                  className="px-4 py-3 border-b border-white/5 hover:bg-white/5 cursor-pointer transition-colors group"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-white truncate">{record.query}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`text-xs ${
                          record.status === 'failed'
                            ? 'text-red-400'
                            : record.status === 'empty'
                              ? 'text-yellow-400'
                              : record.status === 'partial'
                                ? 'text-orange-400'
                                : 'text-cyan'
                        }`}>
                          {record.status === 'failed'
                            ? '失败'
                            : record.status === 'empty'
                              ? '空结果'
                              : record.status === 'partial'
                                ? '部分结果'
                                : `${record.result_count} 只`}
                        </span>
                        {record.strategy_summary && (
                          <span className="text-xs text-muted truncate">{record.strategy_summary.slice(0, 30)}</span>
                        )}
                      </div>
                      {record.error_message && (
                        <p className="text-xs text-red-400/80 truncate mt-1">{record.error_message}</p>
                      )}
                      {record.created_at && (
                        <p className="text-xs text-muted mt-0.5">
                          {new Date(record.created_at).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={(e) => handleDeleteHistory(record.id, e)}
                      className="opacity-0 group-hover:opacity-100 text-muted hover:text-red-400 transition-all p-1"
                      title="删除"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      <StockPriceDetailDrawer
        isOpen={Boolean(selectedStock)}
        stockCode={selectedStock?.code}
        stockName={selectedStock?.name}
        onClose={() => setSelectedStock(null)}
        onOpenAiAnalysis={openAiAnalysis}
      />
    </div>
  );
};

export default ScreenerPage;
