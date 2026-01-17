import Database from "better-sqlite3";
import type { StockPrice } from "./types.js";

export class StockDatabase {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.init();
  }

  private init(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS stock_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        timeframe TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        created_at INTEGER DEFAULT (strftime('%s', 'now')),
        UNIQUE(symbol, timestamp, timeframe)
      )
    `);

    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_symbol_timestamp 
      ON stock_prices(symbol, timestamp)
    `);
  }

  insert(price: StockPrice): void {
    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO stock_prices 
      (symbol, timestamp, timeframe, open, high, low, close, volume)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(
      price.symbol,
      price.timestamp,
      price.timeframe,
      price.open,
      price.high,
      price.low,
      price.close,
      price.volume
    );
  }

  insertMany(prices: StockPrice[]): void {
    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO stock_prices 
      (symbol, timestamp, timeframe, open, high, low, close, volume)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const insertMany = this.db.transaction((items: StockPrice[]) => {
      for (const price of items) {
        stmt.run(
          price.symbol,
          price.timestamp,
          price.timeframe,
          price.open,
          price.high,
          price.low,
          price.close,
          price.volume
        );
      }
    });

    insertMany(prices);
  }

  getLatest(symbol: string, limit = 100): StockPrice[] {
    const stmt = this.db.prepare(`
      SELECT * FROM stock_prices 
      WHERE symbol = ? 
      ORDER BY timestamp DESC 
      LIMIT ?
    `);
    return stmt.all(symbol, limit) as StockPrice[];
  }

  getByTimeRange(
    symbol: string,
    startTime: number,
    endTime: number
  ): StockPrice[] {
    const stmt = this.db.prepare(`
      SELECT * FROM stock_prices 
      WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?
      ORDER BY timestamp ASC
    `);
    return stmt.all(symbol, startTime, endTime) as StockPrice[];
  }

  close(): void {
    this.db.close();
  }
}
