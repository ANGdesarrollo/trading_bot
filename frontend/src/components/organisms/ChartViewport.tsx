import { useEffect, useRef } from 'react';
import { init, dispose, registerIndicator, type Chart, type KLineData, type IndicatorTemplate } from 'klinecharts';
import type { AnnotatedCandle, FadeTrade, PlainCandle } from '../../types/api';

const UP_RUN_BG       = '#ff9800';
const DOWN_RUN_BG     = '#ab47bc';
const UP_BUILDUP_BG   = '#ffcc80';
const DOWN_BUILDUP_BG = '#ce93d8';
const DEFAULT_UP      = '#26a69a';
const DEFAULT_DOWN    = '#ef5350';
const COUNTER_COLOR   = '#42a5f5';

const RUN_BG_ALPHA     = 0.28;
const BUILDUP_BG_ALPHA = 0.14;

const TRADE_WIN_COLOR  = '#2e7d32';
const TRADE_LOSS_COLOR = '#c62828';
const TRADE_LONG_COLOR = '#1565c0';
const TRADE_SHORT_COLOR = '#6a1b9a';

const TP_ZONE_COLOR  = '#26a69a';
const SL_ZONE_COLOR  = '#ef5350';
const ENTRY_LINE_COLOR = '#37474f';
const TP_SL_ZONE_ALPHA = 0.12;

interface IndexedTrade {
  number: number;
  entryIdx: number;
  exitIdx: number;
  direction: 1 | -1;
  isWin: boolean;
  entryPrice: number;
  slPrice: number;
  tpPrice: number;
}

const tradeStore: { byTimestamp: Map<number, IndexedTrade> } = { byTimestamp: new Map() };

const RunColorIndicator: IndicatorTemplate = {
  name: 'runColor',
  calc: (dataList) => dataList.map(() => ({})),
  draw: ({ ctx, chart, bounding, xAxis, yAxis }) => {
    const { from, to } = chart.getVisibleRange();
    const barSpace = chart.getBarSpace();
    const dataList = chart.getDataList() as Array<KLineData & Partial<AnnotatedCandle>>;
    const halfWidth = barSpace.bar / 2;

    const paneTop = 0;
    const paneBottom = bounding.height;

    ctx.save();
    for (let i = from; i < to; i++) {
      const bar = dataList[i];
      const phase = bar?.run_phase;
      if (phase !== 'confirmed' && phase !== 'buildup') continue;

      const x = xAxis.convertToPixel(i);
      const isUp = bar.run_direction === 1;
      const bgColor = phase === 'confirmed'
        ? (isUp ? UP_RUN_BG : DOWN_RUN_BG)
        : (isUp ? UP_BUILDUP_BG : DOWN_BUILDUP_BG);

      ctx.globalAlpha = phase === 'confirmed' ? RUN_BG_ALPHA : BUILDUP_BG_ALPHA;
      ctx.fillStyle = bgColor;
      ctx.fillRect(x - halfWidth, paneTop, halfWidth * 2, paneBottom - paneTop);
    }
    ctx.restore();

    for (let i = from; i < to; i++) {
      const bar = dataList[i];
      if (!bar?.is_counter_bar) continue;
      const x = xAxis.convertToPixel(i);
      const highY = yAxis.convertToPixel(bar.high);
      const dotRadius = 3;
      ctx.beginPath();
      ctx.arc(x, highY - dotRadius - 4, dotRadius, 0, Math.PI * 2);
      ctx.fillStyle = COUNTER_COLOR;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.fill();
      ctx.stroke();
      ctx.lineWidth = 1;
    }

    ctx.save();
    for (let i = from; i < to; i++) {
      const bar = dataList[i];
      const trade = tradeStore.byTimestamp.get(bar.timestamp);
      if (!trade || trade.entryIdx !== i) continue;

      const entryX = xAxis.convertToPixel(i);
      const isLong = trade.direction === 1;
      const arrowColor = isLong ? TRADE_LONG_COLOR : TRADE_SHORT_COLOR;
      const anchorPrice = isLong ? bar.low : bar.high;
      const anchorY = yAxis.convertToPixel(anchorPrice);
      const dir = isLong ? 1 : -1;
      const tip = anchorY + dir * 14;
      const base = anchorY + dir * 26;

      const lastIdx = trade.exitIdx >= 0 ? trade.exitIdx : i;
      const zoneRightX = xAxis.convertToPixel(lastIdx) + halfWidth;
      const zoneLeftX = entryX - halfWidth;
      const zoneWidth = Math.max(zoneRightX - zoneLeftX, halfWidth * 2);

      const entryY = yAxis.convertToPixel(trade.entryPrice);
      const tpY = yAxis.convertToPixel(trade.tpPrice);
      const slY = yAxis.convertToPixel(trade.slPrice);

      ctx.globalAlpha = TP_SL_ZONE_ALPHA;
      ctx.fillStyle = TP_ZONE_COLOR;
      ctx.fillRect(zoneLeftX, Math.min(entryY, tpY), zoneWidth, Math.abs(tpY - entryY));
      ctx.fillStyle = SL_ZONE_COLOR;
      ctx.fillRect(zoneLeftX, Math.min(entryY, slY), zoneWidth, Math.abs(slY - entryY));
      ctx.globalAlpha = 1;

      ctx.beginPath();
      ctx.moveTo(zoneLeftX, entryY);
      ctx.lineTo(zoneRightX, entryY);
      ctx.strokeStyle = ENTRY_LINE_COLOR;
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(entryX, tip);
      ctx.lineTo(entryX - 5, base);
      ctx.lineTo(entryX + 5, base);
      ctx.closePath();
      ctx.fillStyle = arrowColor;
      ctx.fill();

      const labelY = base + dir * 9;
      ctx.font = 'bold 11px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#ffffff';
      ctx.strokeText(String(trade.number), entryX, labelY);
      ctx.fillStyle = arrowColor;
      ctx.fillText(String(trade.number), entryX, labelY);
      ctx.lineWidth = 1;

      if (trade.exitIdx >= 0 && trade.exitIdx < dataList.length) {
        const exitBar = dataList[trade.exitIdx];
        const exitX = xAxis.convertToPixel(trade.exitIdx);
        const exitY = yAxis.convertToPixel(exitBar.close);
        ctx.beginPath();
        ctx.arc(exitX, exitY, 4, 0, Math.PI * 2);
        ctx.fillStyle = trade.isWin ? TRADE_WIN_COLOR : TRADE_LOSS_COLOR;
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        ctx.fill();
        ctx.stroke();
      }
    }
    ctx.restore();
    return false;
  },
};

registerIndicator(RunColorIndicator);

export interface ChartViewportProps {
  candles: PlainCandle[];
  trades?: FadeTrade[];
  symbol?: string;
  timeframe?: string;
  onCrosshairMove?: (barIndex: number | null) => void;
}

function parsePeriod(timeframe: string): { type: 'minute' | 'hour' | 'day'; span: number } {
  const match = timeframe.match(/^(\d+)(m|h|d)$/i);
  if (!match) return { type: 'minute', span: 15 };
  const span = Number(match[1]);
  const unit = match[2].toLowerCase();
  if (unit === 'h') return { type: 'hour', span };
  if (unit === 'd') return { type: 'day', span };
  return { type: 'minute', span };
}

function derivePricePrecision(candles: PlainCandle[]): number {
  if (candles.length === 0) return 2;
  let maxDecimals = 0;
  for (const c of candles.slice(0, 20)) {
    for (const price of [c.open, c.high, c.low, c.close]) {
      const str = price.toString();
      const dotIdx = str.indexOf('.');
      if (dotIdx !== -1) {
        maxDecimals = Math.max(maxDecimals, str.length - dotIdx - 1);
      }
    }
  }
  return maxDecimals || 2;
}

export function ChartViewport({ candles, trades = [], symbol = 'EURUSD', timeframe = '15m', onCrosshairMove }: ChartViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const crosshairRef = useRef(onCrosshairMove);
  const klineDataRef = useRef<KLineData[]>([]);

  crosshairRef.current = onCrosshairMove;

  useEffect(() => {
    if (!containerRef.current) return;
    dispose(containerRef.current);

    const chart = init(containerRef.current);
    if (!chart) return;

    chart.setStyles({
      candle: {
        type: 'candle_solid',
        bar: {
          upColor:        DEFAULT_UP,
          downColor:      DEFAULT_DOWN,
          upBorderColor:  DEFAULT_UP,
          downBorderColor: DEFAULT_DOWN,
          upWickColor:    DEFAULT_UP,
          downWickColor:  DEFAULT_DOWN,
        },
      },
      grid: {
        horizontal: { color: '#e0e0e0' },
        vertical:   { color: '#e0e0e0' },
      },
    });

    chart.subscribeAction('onCrosshairChange', (data: any) => {
      if (data && typeof data.dataIndex === 'number') {
        crosshairRef.current?.(data.dataIndex);
      } else {
        crosshairRef.current?.(null);
      }
    });

    chartRef.current = chart;

    return () => {
      if (containerRef.current) dispose(containerRef.current);
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || candles.length === 0) return;

    const pricePrecision = derivePricePrecision(candles);

    const klineData: KLineData[] = candles.map((c) => ({
      timestamp:      new Date(c.time).getTime(),
      open:           c.open,
      high:           c.high,
      low:            c.low,
      close:          c.close,
      volume:         c.volume,
      in_run:         c.in_run,
      run_direction:  c.run_direction,
      is_counter_bar: c.is_counter_bar,
      run_phase:      c.run_phase ?? null,
    } as KLineData & Partial<AnnotatedCandle>));
    klineDataRef.current = klineData;

    const timestampToIndex = new Map<number, number>();
    klineData.forEach((d, idx) => timestampToIndex.set(d.timestamp, idx));

    tradeStore.byTimestamp.clear();
    trades.forEach((t, idx) => {
      const entryTs = new Date(t.entry_time).getTime();
      const exitTs = new Date(t.exit_time).getTime();
      const entryIdx = timestampToIndex.get(entryTs);
      if (entryIdx === undefined) return;
      const exitIdx = timestampToIndex.get(exitTs) ?? -1;
      tradeStore.byTimestamp.set(entryTs, {
        number: idx + 1,
        entryIdx,
        exitIdx,
        direction: t.direction,
        isWin: t.r_multiple > 0,
        entryPrice: t.entry_price,
        slPrice: t.sl_price,
        tpPrice: t.tp_price,
      });
    });

    chart.setDataLoader({
      getBars: ({ callback }) => {
        callback(klineDataRef.current, { backward: false, forward: false });
      },
    });

    chart.setSymbol({ ticker: symbol, pricePrecision, volumePrecision: 0 });
    chart.setPeriod(parsePeriod(timeframe));

    chart.createIndicator({ name: 'runColor' }, false, { id: 'candle_pane' });
  }, [candles, trades, symbol, timeframe]);

  return (
    <div className="w-full h-full bg-white rounded-lg shadow-sm border border-gray-200">
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
}
