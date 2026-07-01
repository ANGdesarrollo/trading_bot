import type { DatasetsResponse, CandlesResponse, CandlesParams } from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001';

class ApiError extends Error {
  status: number;
  details?: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new ApiError(
      errorData.detail || `HTTP ${response.status}: ${response.statusText}`,
      response.status,
      errorData
    );
  }

  return response.json();
}

export const api = {
  async getDatasets(): Promise<DatasetsResponse> {
    return fetchJson<DatasetsResponse>(`${API_BASE_URL}/api/scan/datasets`);
  },

  async getCandles(params: CandlesParams): Promise<CandlesResponse> {
    const query = new URLSearchParams({ symbol: params.symbol, timeframe: params.timeframe });
    if (params.limit !== undefined) query.set('limit', String(params.limit));
    if (params.provider)            query.set('provider', params.provider);
    return fetchJson<CandlesResponse>(`${API_BASE_URL}/api/scan/candles?${query}`);
  },
};

export { ApiError };
