declare module "@mathieuc/tradingview" {
  interface ClientOptions {
    token?: string;
    signature?: string;
  }

  interface PricePeriod {
    time: number;
    open: number;
    close: number;
    max: number;
    min: number;
    volume: number;
  }

  interface MarketInfos {
    series_id: string;
    name: string;
    full_name: string;
    description: string;
    short_description: string;
    exchange: string;
    currency_id: string;
    type: string;
  }

  interface ChartOptions {
    timeframe?: string;
    range?: number;
    to?: number;
    adjustment?: "splits" | "dividends";
    session?: "regular" | "extended";
    currency?: string;
    type?: "HeikinAshi" | "Renko" | "LineBreak" | "Kagi" | "PointAndFigure" | "Range";
    replay?: number;
  }

  interface Chart {
    periods: PricePeriod[];
    infos: MarketInfos;
    setMarket(symbol: string, options?: ChartOptions): void;
    setSeries(timeframe: string, range?: number, reference?: number): void;
    onSymbolLoaded(callback: () => void): void;
    onUpdate(callback: (changes: string[]) => void): void;
    onError(callback: (...args: any[]) => void): void;
    fetchMore(number?: number): void;
    delete(): void;
  }

  interface Session {
    Chart: new () => Chart;
  }

  class Client {
    constructor(options?: ClientOptions);
    Session: Session;
    end(): void;
  }

  export default {
    Client: Client,
  };

  export { Client };
}
