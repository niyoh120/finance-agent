import TradingView from "@mathieuc/tradingview";
import { StockDatabase } from "./database.js";
import type { Config, StockPrice, TradingViewPeriod } from "./types.js";

interface ChartInstance {
  chart: any;
  symbol: string;
  lastTimestamp: number;
}

export class TradingViewService {
  private client: any;
  private db: StockDatabase;
  private config: Config;
  private charts: Map<string, ChartInstance> = new Map();
  private isRunning = false;

  constructor(config: Config) {
    this.config = config;
    this.db = new StockDatabase(config.databasePath);

    const clientOptions: any = {};
    if (config.tradingviewSession && config.tradingviewSignature) {
      clientOptions.token = config.tradingviewSession;
      clientOptions.signature = config.tradingviewSignature;
    }
    this.client = new TradingView.Client(clientOptions);
  }

  async start(): Promise<void> {
    if (this.isRunning) return;
    this.isRunning = true;

    console.log(
      `[TradingView] Starting service with ${this.config.symbols.length} symbols...`
    );

    for (const symbol of this.config.symbols) {
      this.subscribeSymbol(symbol);
    }
  }

  private subscribeSymbol(symbol: string): void {
    const chart = new this.client.Session.Chart();

    chart.setMarket(symbol, {
      timeframe: this.config.timeframe,
      range: 100,
    });

    chart.onError((...err: any[]) => {
      console.error(`[${symbol}] Chart error:`, ...err);
    });

    chart.onSymbolLoaded(() => {
      const info = chart.infos;
      console.log(
        `[${symbol}] Loaded: ${info.description} (${info.exchange})`
      );
    });

    chart.onUpdate(() => {
      this.handleUpdate(symbol, chart);
    });

    this.charts.set(symbol, {
      chart,
      symbol,
      lastTimestamp: 0,
    });

    console.log(`[${symbol}] Subscribed`);
  }

  private handleUpdate(symbol: string, chart: any): void {
    const periods: TradingViewPeriod[] = chart.periods;
    if (!periods || periods.length === 0) return;

    const chartInstance = this.charts.get(symbol);
    if (!chartInstance) return;

    const newPrices: StockPrice[] = [];

    for (const period of periods) {
      if (period.time <= chartInstance.lastTimestamp) continue;

      newPrices.push({
        symbol,
        timestamp: period.time,
        timeframe: this.config.timeframe,
        open: period.open,
        high: period.max,
        low: period.min,
        close: period.close,
        volume: period.volume,
      });
    }

    if (newPrices.length > 0) {
      this.db.insertMany(newPrices);
      chartInstance.lastTimestamp = Math.max(
        ...newPrices.map((p) => p.timestamp)
      );

      const latest = newPrices[newPrices.length - 1];
      console.log(
        `[${symbol}] ${new Date(latest.timestamp * 1000).toISOString()} ` +
          `O:${latest.open} H:${latest.high} L:${latest.low} C:${latest.close} V:${latest.volume}`
      );
    }
  }

  stop(): void {
    if (!this.isRunning) return;
    this.isRunning = false;

    for (const [symbol, instance] of this.charts) {
      instance.chart.delete();
      console.log(`[${symbol}] Unsubscribed`);
    }
    this.charts.clear();
    this.client.end();
    this.db.close();

    console.log("[TradingView] Service stopped");
  }
}
