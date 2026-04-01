import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { AnalysisResult, AnalysisReport } from '../types/analysis';
import { createVersionedSessionStorage, SESSION_PERSIST_TTL_MS } from '../utils/persist';

interface AnalysisState {
  // 分析状态
  isLoading: boolean;
  result: AnalysisResult | null;
  error: string | null;
  draftStockCode: string;
  priceDetailVisible: boolean;

  // 历史报告视图
  isHistoryView: boolean;
  historyReport: AnalysisReport | null;

  // Actions
  setLoading: (loading: boolean) => void;
  setResult: (result: AnalysisResult | null) => void;
  setError: (error: string | null) => void;
  setDraftStockCode: (value: string) => void;
  setPriceDetailVisible: (value: boolean) => void;
  setHistoryReport: (report: AnalysisReport | null) => void;
  reset: () => void;
  resetToAnalysis: () => void;
}

type PersistedAnalysisState = Pick<
  AnalysisState,
  'draftStockCode' | 'result' | 'priceDetailVisible' | 'isHistoryView' | 'historyReport'
>;

export const useAnalysisStore = create<AnalysisState>()(
  persist(
    (set) => ({
      // 初始状态
      isLoading: false,
      result: null,
      error: null,
      draftStockCode: '',
      priceDetailVisible: false,
      isHistoryView: false,
      historyReport: null,

      // Actions
      setLoading: (loading) => set({ isLoading: loading }),
      setDraftStockCode: (draftStockCode) => set({ draftStockCode }),
      setPriceDetailVisible: (priceDetailVisible) => set({ priceDetailVisible }),

      setResult: (result) =>
        set({
          result,
          error: null,
          isHistoryView: false,
          historyReport: null,
        }),

      setError: (error) => set({ error, isLoading: false }),

      setHistoryReport: (report) =>
        set({
          historyReport: report,
          isHistoryView: true,
          result: null,
          error: null,
          isLoading: false,
        }),

      reset: () =>
        set({
          isLoading: false,
          result: null,
          error: null,
          draftStockCode: '',
          priceDetailVisible: false,
          isHistoryView: false,
          historyReport: null,
        }),

      resetToAnalysis: () =>
        set({
          isHistoryView: false,
          historyReport: null,
        }),
    }),
    {
      name: 'dsa-analysis-store',
      version: 1,
      storage: createJSONStorage<PersistedAnalysisState>(() =>
        createVersionedSessionStorage<PersistedAnalysisState>(1, SESSION_PERSIST_TTL_MS),
      ),
      partialize: (state): PersistedAnalysisState => ({
        draftStockCode: state.draftStockCode,
        result: state.result,
        priceDetailVisible: state.priceDetailVisible,
        isHistoryView: state.isHistoryView,
        historyReport: state.historyReport,
      }),
    },
  ),
);
