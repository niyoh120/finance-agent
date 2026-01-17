/**
 * 股价数据模型
 */
export interface StockPrice {
  id?: number;
  symbol: string;          // 股票代码 (e.g., "NASDAQ:AAPL")
  timestamp: number;       // Unix 时间戳 (秒)
  timeframe: string;       // 时间粒度 (e.g., "1" = 1分钟)
  open: number;            // 开盘价
  high: number;            // 最高价
  low: number;             // 最低价
  close: number;           // 收盘价
  volume: number;          // 成交量
  created_at?: number;     // 记录创建时间
}

/**
 * TradingView 返回的 K 线数据
 */
export interface TradingViewPeriod {
  time: number;
  open: number;
  close: number;
  max: number;    // TradingView 用 max 表示最高价
  min: number;    // TradingView 用 min 表示最低价
  volume: number;
}

/**
 * 市场信息
 */
export interface MarketInfo {
  name: string;
  full_name: string;
  description: string;
  exchange: string;
  currency_id: string;
  type: string;
}

/**
 * 配置接口
 */
export interface Config {
  symbols: string[];           // 要订阅的股票代码列表
  timeframe: string;           // 时间粒度 (默认 "1" = 1分钟)
  tradingviewSession?: string; // TradingView session cookie (可选，用于 premium 功能)
  tradingviewSignature?: string; // TradingView signature cookie
  databasePath: string;        // 数据库路径
}
