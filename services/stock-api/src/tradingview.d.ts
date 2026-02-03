declare module '@mathieuc/tradingview' {
  export type MarketType = 'stock' | 'futures' | 'forex' | 'cfd' | 'crypto' | 'index' | 'economic';

  export interface SearchMarketResult {
    id: string;
    exchange: string;
    fullExchange: string;
    symbol: string;
    description: string;
    type: string;
    getTA?: () => Promise<unknown>;
  }

  export interface ClientOptions {
    token?: string;
    signature?: string;
  }

  export interface QuoteSession {
    Market: new (symbol: string) => Market;
  }

  export interface Market {
    onData(callback: (data: unknown) => void): void;
    onError(callback: (err: unknown) => void): void;
  }

  export interface ChartPeriod {
    time: number;
    open: number;
    close: number;
    max: number;
    min: number;
    volume?: number;
  }

  export interface ChartInfo {
    description?: string;
    full_name?: string;
    exchange?: string;
    type?: string;
    timezone?: string;
    currency_code?: string;
  }

  export interface ChartMarketOptions {
    timeframe?: string;
    range?: number;
    to?: number;
    replay?: number;
    type?: string;
  }

  export interface ChartStudy {
    periods: unknown[];
    graphic?: unknown;
    strategyReport?: unknown;

    onReady(callback: () => void): void;
    onUpdate(callback: () => void): void;
    onError(callback: (...err: unknown[]) => void): void;
  }

  export interface ChartSession {
    periods: ChartPeriod[];
    infos: ChartInfo;

    setMarket(symbol: string, options?: ChartMarketOptions): void;
    setSeries(timeframe: string): void;
    fetchMore(count: number): void;

    onUpdate(callback: (changes?: unknown) => void): void;
    onError(callback: (...err: unknown[]) => void): void;
    onSymbolLoaded(callback: () => void): void;

    delete(): void;

    Study: new (indicator: unknown) => ChartStudy;
  }

  export class BuiltInIndicator {
    constructor(type: string);
    type: string;
    setOption(key: string, value: unknown): void;
  }

  export interface PineIndicator {
    pineId: string;
    pineVersion: string;
    description: string;
    shortDescription: string;
    inputs: Record<string, unknown>;
    plots: Record<string, string>;

    setOption(key: string, value: unknown): void;
  }

  export class Client {
    constructor(options?: ClientOptions);
    Session: {
      Quote: new (options?: { fields?: string }) => QuoteSession;
      Chart: new () => ChartSession;
    };

    end(): void;
  }

  export function getIndicator(
    id: string,
    version?: 'last' | string,
    session?: string,
    signature?: string
  ): Promise<PineIndicator>;

  export function getPrivateIndicators(session: string, signature?: string): Promise<Array<{ get: () => Promise<PineIndicator> } & Record<string, unknown>>>;

  export function searchIndicator(search?: string): Promise<unknown[]>;

  export function searchMarketV3(
    search: string,
    filter?: MarketType | '',
    offset?: number
  ): Promise<SearchMarketResult[]>;

  export function getTA(id: string): Promise<unknown>;

  const TradingView: {
    Client: typeof Client;
    BuiltInIndicator: typeof BuiltInIndicator;
    getIndicator: typeof getIndicator;
    getPrivateIndicators: typeof getPrivateIndicators;
    searchIndicator: typeof searchIndicator;
    searchMarketV3: typeof searchMarketV3;
    getTA: typeof getTA;
  };

  export default TradingView;
}
