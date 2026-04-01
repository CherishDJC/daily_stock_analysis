import apiClient from './index';

export interface ScreenerStreamPayload {
  query: string;
  skills?: string[];
}

export interface ScreenerProgressStep {
  type: string;
  step?: number;
  tool?: string;
  display_name?: string;
  success?: boolean;
  duration?: number;
  message?: string;
}

export interface ScreenerResult {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  signal: string;
  signal_score: number;
  reason: string;
  sector: string;
  pe_ratio?: number;
  market_cap?: string;
  key_indicators?: {
    ma_alignment?: string;
    bias_ma5?: number;
    volume_ratio?: number;
    profit_ratio?: number;
  };
}

export interface ScreenerDashboard {
  query: string;
  market_overview: {
    hot_sectors: string[];
    cold_sectors: string[];
    market_style: string;
  };
  results: ScreenerResult[];
  strategy_summary: string;
  risk_warning: string;
  action_plan: string;
}

export interface ScreenerHistoryItem {
  id: number;
  query: string;
  result_count: number;
  strategy_summary: string | null;
  status?: string | null;
  provider?: string | null;
  error_message?: string | null;
  created_at: string | null;
}

export interface ScreenerHistoryDetail {
  id: number;
  query: string;
  conditions: unknown;
  dashboard?: ScreenerDashboard | null;
  results: ScreenerResult[] | null;
  report_markdown?: string | null;
  result_count: number;
  strategy_summary: string | null;
  risk_warning: string | null;
  status?: string | null;
  provider?: string | null;
  error_message?: string | null;
  total_steps: number;
  total_tokens: number;
  created_at: string | null;
}

export interface ScreenerSavePayload {
  query: string;
  dashboard?: ScreenerDashboard;
  results?: unknown;
  report_markdown?: string;
  status?: string;
  provider?: string;
  error_message?: string;
  result_count?: number;
  strategy_summary?: string;
  risk_warning?: string;
  conditions?: unknown;
  total_steps?: number;
  total_tokens?: number;
}

export const screenerApi = {
  /**
   * Stream screener results via SSE.
   * Returns the raw Response for caller to consume SSE events.
   */
  async streamScreener(payload: ScreenerStreamPayload): Promise<Response> {
    const baseUrl = apiClient.defaults.baseURL || '';
    const response = await fetch(`${baseUrl}/api/v1/agent/screener/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      const detail = (errData as { detail?: string }).detail || `HTTP ${response.status}`;
      throw new Error(detail);
    }
    return response;
  },

  /** Get screener history list */
  async getHistory(limit = 20, offset = 0): Promise<{ records: ScreenerHistoryItem[] }> {
    const res = await apiClient.get('/api/v1/agent/screener/history', { params: { limit, offset } });
    return res.data;
  },

  /** Get screener history detail */
  async getDetail(recordId: number): Promise<ScreenerHistoryDetail> {
    const res = await apiClient.get(`/api/v1/agent/screener/history/${recordId}`);
    return res.data;
  },

  /** Save screener result */
  async save(payload: ScreenerSavePayload): Promise<{ id: number }> {
    const res = await apiClient.post('/api/v1/agent/screener/history', payload);
    return res.data;
  },

  /** Delete screener history record */
  async deleteRecord(recordId: number): Promise<void> {
    await apiClient.delete(`/api/v1/agent/screener/history/${recordId}`);
  },
};
