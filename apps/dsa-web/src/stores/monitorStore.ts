import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import { createVersionedSessionStorage, SESSION_PERSIST_TTL_MS } from '../utils/persist';

type MonitorSelectedStock = {
  stockCode: string;
  stockName?: string | null;
} | null;

type PricePanelViewMode = 'minute' | 'daily';

interface MonitorState {
  selectedStock: MonitorSelectedStock;
  pricePanelViewMode: PricePanelViewMode;
  historyDays: string;
  minuteInterval: string;
  historyFullscreen: boolean;
  setSelectedStock: (value: MonitorSelectedStock) => void;
  setPricePanelViewMode: (value: PricePanelViewMode) => void;
  setHistoryDays: (value: string) => void;
  setMinuteInterval: (value: string) => void;
  setHistoryFullscreen: (value: boolean) => void;
  resetDetail: () => void;
}

type PersistedMonitorState = Pick<
  MonitorState,
  'selectedStock' | 'pricePanelViewMode' | 'historyDays' | 'minuteInterval' | 'historyFullscreen'
>;

export const useMonitorStore = create<MonitorState>()(
  persist(
    (set) => ({
      selectedStock: null,
      pricePanelViewMode: 'minute',
      historyDays: '60',
      minuteInterval: '1',
      historyFullscreen: false,
      setSelectedStock: (selectedStock) => set({ selectedStock }),
      setPricePanelViewMode: (pricePanelViewMode) => set({ pricePanelViewMode }),
      setHistoryDays: (historyDays) => set({ historyDays }),
      setMinuteInterval: (minuteInterval) => set({ minuteInterval }),
      setHistoryFullscreen: (historyFullscreen) => set({ historyFullscreen }),
      resetDetail: () =>
        set({
          selectedStock: null,
          pricePanelViewMode: 'minute',
          historyDays: '60',
          minuteInterval: '1',
          historyFullscreen: false,
        }),
    }),
    {
      name: 'dsa-monitor-store',
      version: 1,
      storage: createJSONStorage<PersistedMonitorState>(() =>
        createVersionedSessionStorage<PersistedMonitorState>(1, SESSION_PERSIST_TTL_MS),
      ),
      partialize: (state): PersistedMonitorState => ({
        selectedStock: state.selectedStock,
        pricePanelViewMode: state.pricePanelViewMode,
        historyDays: state.historyDays,
        minuteInterval: state.minuteInterval,
        historyFullscreen: state.historyFullscreen,
      }),
    },
  ),
);
