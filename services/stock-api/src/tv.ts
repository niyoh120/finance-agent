import TradingView from '@mathieuc/tradingview';
import type { BuiltInIndicator, Client, PineIndicator } from '@mathieuc/tradingview';
import { Candle, IndicatorResult, QuoteData, TechnicalAnalysis } from './types.js';

type TradingViewModule = typeof TradingView;

function createClient(): Client {
  const token = process.env.TV_SESSION;
  const signature = process.env.TV_SIGNATURE;

  if (token) {
    return new TradingView.Client({
      token,
      signature
    });
  }

  return new TradingView.Client();
}

function safeErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

async function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  let timeout: NodeJS.Timeout | undefined;

  const timeoutPromise = new Promise<never>((_, reject) => {
    timeout = setTimeout(() => reject(new Error(message)), ms);
  });

  try {
    return await Promise.race([promise, timeoutPromise]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}

export async function getQuote(symbol: string): Promise<QuoteData> {
  return withTimeout(
    new Promise((resolve, reject) => {
      const client = createClient();
      const session = new client.Session.Quote({ fields: 'all' });
      const market = new session.Market(symbol);

      let done = false;

      const cleanup = () => {
        if (done) return;
        done = true;
        client.end();
      };

      market.onData((data: unknown) => {
        if (done || typeof data !== 'object' || data === null) return;

        const d = data as Record<string, unknown>;
        if (d.lp === undefined) return;

        const num = (value: unknown, fallback = 0): number => {
          return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
        };

        const str = (value: unknown, fallback = ''): string => {
          return typeof value === 'string' ? value : fallback;
        };

        const quote: QuoteData = {
          symbol,
          price: num(d.lp),
          volume: num(d.volume),
          change: num(d.ch),
          changePercent: num(d.chp),
          high: num(d.high_price),
          low: num(d.low_price),
          open: num(d.open_price),
          prevClose: num(d.prev_close_price),
          bid: num(d.bid),
          ask: num(d.ask),
          status: str(d.status, 'unknown'),
          timestamp: Date.now()
        };

        cleanup();
        resolve(quote);
      });

      market.onError((err: unknown) => {
        if (done) return;
        cleanup();
        reject(err);
      });
    }),
    10000,
    `Timeout fetching quote for ${symbol}`
  );
}

export async function getHistory(params: {
  symbol: string;
  timeframe: string;
  range: number;
  to?: number;
}): Promise<Candle[]> {
  const { symbol, timeframe, range, to } = params;

  return withTimeout(
    new Promise((resolve, reject) => {
      const client = createClient();
      const chart = new client.Session.Chart();

      let done = false;

      const cleanup = () => {
        if (done) return;
        done = true;
        try {
          chart.delete?.();
        } finally {
          client.end();
        }
      };

      chart.onError((...err: unknown[]) => {
        if (done) return;
        cleanup();
        reject(new Error(safeErrorMessage(err[0], `Failed to load chart for ${symbol}`)));
      });

      chart.onUpdate(() => {
        if (done) return;
        if (!chart.periods?.length) return;

        const candles: Candle[] = chart.periods
          .map((p: any) => ({
            time: p.time,
            timestamp: p.time * 1000,
            open: p.open,
            high: p.max,
            low: p.min,
            close: p.close,
            volume: p.volume
          }))
          .filter((c: Candle) => Number.isFinite(c.time) && Number.isFinite(c.close));

        cleanup();
        resolve(candles);
      });

      chart.setMarket(symbol, {
        timeframe,
        range,
        ...(to ? { to } : {})
      });
    }),
    20000,
    `Timeout fetching history for ${symbol}`
  );
}

export async function getTechnicalAnalysis(symbol: string): Promise<TechnicalAnalysis> {
  return (await TradingView.getTA(symbol)) as TechnicalAnalysis;
}

export async function getIndicator(params: {
  symbol: string;
  timeframe: string;
  range: number;
  indicatorId: string;
  to?: number;
  options?: Record<string, unknown>;
}): Promise<IndicatorResult> {
  const { symbol, timeframe, range, indicatorId, to, options } = params;

  const session = process.env.TV_SESSION ?? '';
  const signature = process.env.TV_SIGNATURE ?? '';

  const indicator: PineIndicator | BuiltInIndicator = indicatorId.includes('@')
    ? new TradingView.BuiltInIndicator(indicatorId)
    : await TradingView.getIndicator(indicatorId, 'last', session, signature);

  if (options) {
    Object.entries(options).forEach(([key, value]) => {
      indicator.setOption(key, value);
    });
  }

  return withTimeout(
    new Promise((resolve, reject) => {
      const client = createClient();
      const chart = new client.Session.Chart();

      let done = false;

      const cleanup = () => {
        if (done) return;
        done = true;
        try {
          chart.delete?.();
        } finally {
          client.end();
        }
      };

      chart.onError((...err: unknown[]) => {
        if (done) return;
        cleanup();
        reject(new Error(safeErrorMessage(err[0], `Failed to load chart for ${symbol}`)));
      });

      chart.setMarket(symbol, {
        timeframe,
        range,
        ...(to ? { to } : {})
      });

      const study = new chart.Study(indicator);

      study.onError((...err: unknown[]) => {
        if (done) return;
        cleanup();
        reject(new Error(safeErrorMessage(err[0], `Failed to load indicator ${indicatorId}`)));
      });

      study.onUpdate(() => {
        if (done) return;
        if (!chart.periods?.length) return;
        if (!study.periods?.length) return;

        const candles: Candle[] = chart.periods
          .map((p: any) => ({
            time: p.time,
            timestamp: p.time * 1000,
            open: p.open,
            high: p.max,
            low: p.min,
            close: p.close,
            volume: p.volume
          }))
          .filter((c: Candle) => Number.isFinite(c.time) && Number.isFinite(c.close));
 
        const result: IndicatorResult = {
          symbol,
          timeframe,
          range,
          indicatorId,
          candles,
          periods: study.periods,
          plots: 'plots' in indicator ? indicator.plots : undefined,
          strategyReport: study.strategyReport,
          graphic: study.graphic
        };

        cleanup();
        resolve(result);
      });
    }),
    30000,
    `Timeout fetching indicator ${indicatorId} for ${symbol}`
  );
}

export async function getPrivateIndicators(): Promise<Array<{ id: string; version: string; name: string; access: string; type: string }>> {
  const session = process.env.TV_SESSION;
  if (!session) {
    throw new Error('TV_SESSION is required to fetch private indicators');
  }

  const signature = process.env.TV_SIGNATURE ?? '';
  const list = await TradingView.getPrivateIndicators(session, signature);

  return list.map((i: any) => ({
    id: i.id,
    version: i.version,
    name: i.name,
    access: i.access,
    type: i.type
  }));
}
