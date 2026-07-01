import { useState, useEffect, useCallback } from 'react';
import { ChartViewport } from '../components/organisms/ChartViewport';
import { Button } from '../components/atoms/Button';
import { api, ApiError } from '../services/api';
import type { CandlesResponse, DatasetInfo } from '../types/api';

const DEFAULT_LIMIT = 500;

export default function ScanPage() {
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([]);

  const [selectedSymbol, setSelectedSymbol] = useState('EURUSD');
  const [selectedTimeframe, setSelectedTimeframe] = useState('15m');

  const [candlesData, setCandlesData] = useState<CandlesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getDatasets().then((res) => {
      setDatasets(res.datasets);
      const sorted = [...res.symbols].sort();
      setAvailableSymbols(sorted);
      if (sorted.length > 0 && !sorted.includes(selectedSymbol)) {
        setSelectedSymbol(sorted[0]);
      }
    }).catch(() => {});
  }, []);

  const timeframesForSymbol = datasets
    .filter((d) => d.symbol === selectedSymbol)
    .map((d) => d.timeframe);

  useEffect(() => {
    if (timeframesForSymbol.length === 0) return;
    if (!timeframesForSymbol.includes(selectedTimeframe)) {
      setSelectedTimeframe(timeframesForSymbol.includes('15m') ? '15m' : timeframesForSymbol[0]);
    }
  }, [selectedSymbol, datasets]);

  const loadCandles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getCandles({
        symbol: selectedSymbol,
        timeframe: selectedTimeframe,
        limit: DEFAULT_LIMIT,
      });
      setCandlesData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unknown error occurred');
      setCandlesData(null);
    } finally {
      setLoading(false);
    }
  }, [selectedSymbol, selectedTimeframe]);

  useEffect(() => {
    loadCandles();
  }, []);

  const displayCandles = candlesData?.candles ?? [];

  return (
    <div className="flex flex-col h-full min-h-0 p-4 gap-4 bg-gray-50">
      <div className="flex items-end gap-3 flex-wrap">
        <label className="flex flex-col text-sm text-gray-700">
          Symbol
          <select
            className="mt-1 rounded border border-gray-300 px-3 py-2 bg-white"
            value={selectedSymbol}
            onChange={(e) => setSelectedSymbol(e.target.value)}
          >
            {(availableSymbols.length > 0 ? availableSymbols : [selectedSymbol]).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col text-sm text-gray-700">
          Timeframe
          <select
            className="mt-1 rounded border border-gray-300 px-3 py-2 bg-white"
            value={selectedTimeframe}
            onChange={(e) => setSelectedTimeframe(e.target.value)}
          >
            {(timeframesForSymbol.length > 0 ? timeframesForSymbol : [selectedTimeframe]).map((tf) => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>
        </label>

        <Button onClick={loadCandles} disabled={loading}>
          {loading ? 'Loading…' : 'Load'}
        </Button>

        {candlesData && (
          <span className="text-sm text-gray-500 ml-auto">
            {candlesData.meta.bars} bars · {candlesData.meta.symbol} {candlesData.meta.timeframe}
          </span>
        )}
      </div>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 text-red-700 px-4 py-2 text-sm">
          {error}
        </div>
      )}

      <div className="flex-1 min-h-0">
        {displayCandles.length > 0 ? (
          <ChartViewport
            candles={displayCandles}
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400">
            {loading ? 'Loading candles…' : 'No candles to display'}
          </div>
        )}
      </div>
    </div>
  );
}
