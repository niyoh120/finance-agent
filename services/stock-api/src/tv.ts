import TradingView from '@mathieuc/tradingview';
import { QuoteData } from './types.js';

export async function getQuote(symbol: string): Promise<QuoteData> {
  return new Promise((resolve, reject) => {
    const client = new TradingView.Client();
    const session = new client.Session.Quote({ fields: 'all' });
    const market = new session.Market(symbol);

    let resolved = false;

    // Timeout safety
    const timeout = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        client.end();
        reject(new Error(`Timeout fetching quote for ${symbol}`));
      }
    }, 10000); // 10s timeout

    market.onData((data: any) => {
      // Check if we have valid price data (lp = last price)
      if (data.lp !== undefined && !resolved) {
        resolved = true;
        clearTimeout(timeout);
        
        const quote: QuoteData = {
          symbol: symbol,
          price: data.lp,
          volume: data.volume,
          change: data.ch,
          changePercent: data.chp,
          high: data.high_price,
          low: data.low_price,
          open: data.open_price,
          prevClose: data.prev_close_price,
          bid: data.bid,
          ask: data.ask,
          status: data.status,
          timestamp: Date.now()
        };

        client.end();
        resolve(quote);
      }
    });

    market.onError((err: any) => {
      if (!resolved) {
        resolved = true;
        clearTimeout(timeout);
        client.end();
        reject(err);
      }
    });
  });
}
