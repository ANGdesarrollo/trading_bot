export interface AnnotatedCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  in_run: boolean;
  run_direction: 1 | -1 | 0;
  run_length: number;
  directionality: number;
  displacement_pip: number;
  displacement_atr: number;
  is_counter_bar: boolean;
  run_phase?: 'buildup' | 'confirmed' | null;
}

export interface FadeTrade {
  entry_time: string;
  exit_time: string;
  direction: 1 | -1;
  entry_price: number;
  sl_price: number;
  tp_price: number;
  exit_price: number;
  outcome: 'tp' | 'sl' | 'timeout';
  r_multiple: number;
}

export interface DatasetInfo {
  symbol: string;
  timeframe: string;
}

export interface DatasetsResponse {
  datasets: DatasetInfo[];
  symbols: string[];
}

export interface PlainCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  in_run?: boolean;
  run_direction?: 1 | -1 | 0;
  run_length?: number;
  directionality?: number;
  displacement_pip?: number;
  displacement_atr?: number;
  is_counter_bar?: boolean;
  run_phase?: 'buildup' | 'confirmed' | null;
}

export interface CandlesMeta {
  symbol: string;
  timeframe: string;
  bars: number;
}

export interface CandlesResponse {
  meta: CandlesMeta;
  candles: PlainCandle[];
}

export interface CandlesParams {
  symbol: string;
  timeframe: string;
  limit?: number;
  provider?: string;
}
