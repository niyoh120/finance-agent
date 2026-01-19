export interface QuoteData {
  symbol: string;
  price: number;
  volume: number;
  change: number;
  changePercent: number;
  high: number;
  low: number;
  open: number;
  prevClose: number;
  bid: number;
  ask: number;
  status: string;
  timestamp: number;
}

export interface Candle {
  time: number;
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface TechnicalAnalysis {
  [timeframe: string]: {
    Other: number;
    All: number;
    MA: number;
  };
}

export interface IndicatorResult {
  symbol: string;
  timeframe: string;
  range: number;
  indicatorId: string;
  candles: Candle[];
  periods: unknown[];
  plots?: Record<string, string>;
  strategyReport?: unknown;
  graphic?: unknown;
}
