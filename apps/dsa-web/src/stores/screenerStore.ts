import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { ScreenerDashboard } from '../api/screener';
import { createVersionedSessionStorage, SESSION_PERSIST_TTL_MS } from '../utils/persist';

interface ScreenerState {
  input: string;
  selectedStrategy: string;
  dashboard: ScreenerDashboard | null;
  report: string;
  error: string | null;
  selectedStock: { code: string; name?: string | null } | null;
  setInput: (value: string) => void;
  setSelectedStrategy: (value: string) => void;
  setDashboard: (value: ScreenerDashboard | null) => void;
  setReport: (value: string) => void;
  setError: (value: string | null) => void;
  setSelectedStock: (value: { code: string; name?: string | null } | null) => void;
  resetResult: () => void;
}

type PersistedScreenerState = Pick<
  ScreenerState,
  'input' | 'selectedStrategy' | 'dashboard' | 'report' | 'error' | 'selectedStock'
>;

export const useScreenerStore = create<ScreenerState>()(
  persist(
    (set) => ({
      input: '',
      selectedStrategy: '',
      dashboard: null,
      report: '',
      error: null,
      selectedStock: null,
      setInput: (input) => set({ input }),
      setSelectedStrategy: (selectedStrategy) => set({ selectedStrategy }),
      setDashboard: (dashboard) => set({ dashboard }),
      setReport: (report) => set({ report }),
      setError: (error) => set({ error }),
      setSelectedStock: (selectedStock) => set({ selectedStock }),
      resetResult: () =>
        set({
          dashboard: null,
          report: '',
          error: null,
          selectedStock: null,
        }),
    }),
    {
      name: 'dsa-screener-store',
      version: 1,
      storage: createJSONStorage<PersistedScreenerState>(() =>
        createVersionedSessionStorage<PersistedScreenerState>(1, SESSION_PERSIST_TTL_MS),
      ),
      partialize: (state): PersistedScreenerState => ({
        input: state.input,
        selectedStrategy: state.selectedStrategy,
        dashboard: state.dashboard,
        report: state.report,
        error: state.error,
        selectedStock: state.selectedStock,
      }),
    },
  ),
);
