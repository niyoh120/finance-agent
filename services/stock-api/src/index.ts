import Fastify from "fastify";
import { getHistory, getIndicator, getPrivateIndicators, getQuote, getTechnicalAnalysis, searchMarkets } from "./tv.js";

const fastify = Fastify({
  logger: true,
});

const PORT = parseInt(process.env.FA_STOCK_API_PORT || "3000", 10);

function asInt(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  const parsed = parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asString(value: string | undefined, fallback: string): string {
  return value && value.trim() ? value.trim() : fallback;
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

function historyErrorStatus(err: unknown): number {
  const msg = errorMessage(err, "");
  if (!msg) return 500;

  if (msg.startsWith("Timeout fetching history")) return 504;
  if (msg.includes("Failed to load chart for")) return 404;

  return 500;
}

const MARKET_TYPES = new Set(["stock", "futures", "forex", "cfd", "crypto", "index", "economic"]);

type OpenApiDoc = Record<string, unknown>;

function buildOpenApiDoc(): OpenApiDoc {
  return {
    openapi: "3.0.3",
    info: {
      title: "stock-api",
      version: "1.0.0",
    },
    paths: {
      "/health": {
        get: {
          summary: "Health check",
          responses: {
            200: {
              description: "OK",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      status: { type: "string" },
                    },
                    required: ["status"],
                  },
                },
              },
            },
          },
        },
      },
      "/quote": {
        get: {
          summary: "Get realtime quote",
          parameters: [
            {
              name: "symbol",
              in: "query",
              required: true,
              schema: { type: "string" },
              example: "NASDAQ:AAPL",
            },
          ],
          responses: {
            200: {
              description: "Quote",
              content: {
                "application/json": {
                  schema: {
                    $ref: "#/components/schemas/QuoteData",
                  },
                },
              },
            },
            400: { $ref: "#/components/responses/BadRequest" },
            500: { $ref: "#/components/responses/InternalError" },
          },
        },
      },
      "/history": {
        get: {
          summary: "Get historical candles (OHLCV)",
          parameters: [
            {
              name: "symbol",
              in: "query",
              required: true,
              schema: { type: "string" },
              example: "NASDAQ:AAPL",
            },
            {
              name: "timeframe",
              in: "query",
              required: false,
              schema: { type: "string", default: "D" },
              example: "D",
            },
            {
              name: "range",
              in: "query",
              required: false,
              schema: {
                type: "integer",
                default: 200,
                minimum: 1,
              },
              example: 200,
            },
            {
              name: "to",
              in: "query",
              required: false,
              schema: { type: "integer", minimum: 1 },
              description: "Unix time in seconds (end timestamp)",
              example: 1700000000,
            },
          ],
          responses: {
            200: {
              description: "Candles",
              content: {
                "application/json": {
                  schema: {
                    $ref: "#/components/schemas/HistoryResponse",
                  },
                },
              },
            },
            400: { $ref: "#/components/responses/BadRequest" },
            404: { $ref: "#/components/responses/NotFound" },
            504: { $ref: "#/components/responses/GatewayTimeout" },
            500: { $ref: "#/components/responses/InternalError" },
          },
        },
      },
      "/v0/searchMarket": {
        get: {
          summary: "Search TradingView markets",
          parameters: [
            {
              name: "q",
              in: "query",
              required: true,
              schema: { type: "string" },
              description: "Search query (ticker, name, or EXCHANGE: prefix)",
              example: "WMT",
            },
            {
              name: "type",
              in: "query",
              required: false,
              schema: {
                type: "string",
                enum: ["stock", "futures", "forex", "cfd", "crypto", "index", "economic"],
              },
              description: "Optional market type filter",
              example: "stock",
            },
            {
              name: "offset",
              in: "query",
              required: false,
              schema: { type: "integer", default: 0, minimum: 0 },
              description: "Pagination offset",
              example: 0,
            },
            {
              name: "limit",
              in: "query",
              required: false,
              schema: {
                type: "integer",
                default: 10,
                minimum: 1,
                maximum: 50,
              },
              description: "Max number of results to return",
              example: 10,
            },
          ],
          responses: {
            200: {
              description: "Search results",
              content: {
                "application/json": {
                  schema: {
                    $ref: "#/components/schemas/SearchResponse",
                  },
                },
              },
            },
            400: { $ref: "#/components/responses/BadRequest" },
            500: { $ref: "#/components/responses/InternalError" },
          },
        },
      },
      "/indicator": {
        get: {
          summary: "Get indicator values",
          parameters: [
            {
              name: "symbol",
              in: "query",
              required: true,
              schema: { type: "string" },
              example: "NASDAQ:AAPL",
            },
            {
              name: "indicatorId",
              in: "query",
              required: true,
              schema: { type: "string" },
              example: "STD;EMA",
            },
            {
              name: "timeframe",
              in: "query",
              required: false,
              schema: { type: "string", default: "D" },
              example: "D",
            },
            {
              name: "range",
              in: "query",
              required: false,
              schema: {
                type: "integer",
                default: 200,
                minimum: 1,
              },
              example: 200,
            },
            {
              name: "to",
              in: "query",
              required: false,
              schema: { type: "integer", minimum: 1 },
              description: "Unix time in seconds (end timestamp)",
              example: 1700000000,
            },
            {
              name: "options",
              in: "query",
              required: false,
              schema: { type: "string" },
              description: "JSON string of indicator options (inputs)",
            },
          ],
          responses: {
            200: {
              description: "Indicator result",
              content: {
                "application/json": {
                  schema: {
                    $ref: "#/components/schemas/IndicatorResult",
                  },
                },
              },
            },
            400: { $ref: "#/components/responses/BadRequest" },
            500: { $ref: "#/components/responses/InternalError" },
          },
        },
      },
      "/ta": {
        get: {
          summary: "Get TradingView Technical Analysis summary",
          parameters: [
            {
              name: "symbol",
              in: "query",
              required: true,
              schema: { type: "string" },
              example: "NASDAQ:AAPL",
            },
          ],
          responses: {
            200: {
              description: "TA results by timeframe",
              content: {
                "application/json": {
                  schema: {
                    $ref: "#/components/schemas/TechnicalAnalysis",
                  },
                },
              },
            },
            400: { $ref: "#/components/responses/BadRequest" },
            500: { $ref: "#/components/responses/InternalError" },
          },
        },
      },
      "/indicators": {
        get: {
          summary: "List all available indicator IDs and their descriptions",
          responses: {
            200: {
              description: "Available indicators",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    properties: {
                      standard: {
                        type: "array",
                        items: {
                          $ref: "#/components/schemas/IndicatorInfo",
                        },
                      },
                      builtin: {
                        type: "array",
                        items: {
                          $ref: "#/components/schemas/IndicatorInfo",
                        },
                      },
                    },
                    required: ["standard", "builtin"],
                  },
                },
              },
            },
          },
        },
      },
      "/indicators/private": {
        get: {
          summary: "List private indicators for current account",
          responses: {
            200: {
              description: "Private indicators",
              content: {
                "application/json": {
                  schema: {
                    type: "array",
                    items: {
                      $ref: "#/components/schemas/PrivateIndicator",
                    },
                  },
                },
              },
            },
            500: { $ref: "#/components/responses/InternalError" },
          },
        },
      },
      "/openapi.json": {
        get: {
          summary: "OpenAPI spec",
          responses: {
            200: {
              description: "OpenAPI document",
              content: {
                "application/json": {
                  schema: { type: "object" },
                },
              },
            },
          },
        },
      },
    },
    components: {
      schemas: {
        ErrorResponse: {
          type: "object",
          additionalProperties: false,
          properties: { error: { type: "string" } },
          required: ["error"],
        },
        Candle: {
          type: "object",
          additionalProperties: false,
          properties: {
            time: { type: "integer" },
            timestamp: { type: "integer" },
            open: { type: "number" },
            high: { type: "number" },
            low: { type: "number" },
            close: { type: "number" },
            volume: { type: "number", nullable: true },
          },
          required: ["time", "timestamp", "open", "high", "low", "close"],
        },
        QuoteData: {
          type: "object",
          additionalProperties: false,
          properties: {
            symbol: { type: "string" },
            price: { type: "number" },
            volume: { type: "number" },
            change: { type: "number" },
            changePercent: { type: "number" },
            high: { type: "number" },
            low: { type: "number" },
            open: { type: "number" },
            prevClose: { type: "number" },
            bid: { type: "number" },
            ask: { type: "number" },
            status: { type: "string" },
            timestamp: { type: "integer" },
          },
          required: [
            "symbol",
            "price",
            "volume",
            "change",
            "changePercent",
            "high",
            "low",
            "open",
            "prevClose",
            "bid",
            "ask",
            "status",
            "timestamp",
          ],
        },
        HistoryResponse: {
          type: "object",
          additionalProperties: false,
          properties: {
            symbol: { type: "string" },
            timeframe: { type: "string" },
            range: { type: "integer" },
            to: { type: "integer", nullable: true },
            candles: {
              type: "array",
              items: { $ref: "#/components/schemas/Candle" },
            },
          },
          required: ["symbol", "timeframe", "range", "candles"],
        },
        SearchMarket: {
          type: "object",
          additionalProperties: false,
          properties: {
            id: { type: "string" },
            exchange: { type: "string" },
            full_exchange: { type: "string" },
            symbol: { type: "string" },
            description: { type: "string" },
            type: { type: "string" },
          },
          required: ["id", "exchange", "full_exchange", "symbol", "description", "type"],
        },
        SearchResponse: {
          type: "object",
          additionalProperties: false,
          properties: {
            query: { type: "string" },
            type: { type: "string", nullable: true },
            offset: { type: "integer" },
            limit: { type: "integer" },
            count: { type: "integer" },
            results: {
              type: "array",
              items: {
                $ref: "#/components/schemas/SearchMarket",
              },
            },
          },
          required: ["query", "offset", "limit", "count", "results"],
        },
        TechnicalAnalysis: {
          type: "object",
          additionalProperties: {
            type: "object",
            additionalProperties: false,
            properties: {
              Other: { type: "number" },
              All: { type: "number" },
              MA: { type: "number" },
            },
            required: ["Other", "All", "MA"],
          },
        },
        IndicatorResult: {
          type: "object",
          additionalProperties: false,
          properties: {
            symbol: { type: "string" },
            timeframe: { type: "string" },
            range: { type: "integer" },
            indicatorId: { type: "string" },
            candles: {
              type: "array",
              items: { $ref: "#/components/schemas/Candle" },
            },
            periods: {
              type: "array",
              items: {
                type: "object",
                additionalProperties: true,
              },
            },
            plots: {
              type: "object",
              additionalProperties: { type: "string" },
              nullable: true,
            },
            strategyReport: {
              type: "object",
              additionalProperties: true,
              nullable: true,
            },
            graphic: {
              type: "object",
              additionalProperties: true,
              nullable: true,
            },
          },
          required: ["symbol", "timeframe", "range", "indicatorId", "candles", "periods"],
        },
        PrivateIndicator: {
          type: "object",
          additionalProperties: false,
          properties: {
            id: { type: "string" },
            version: { type: "string" },
            name: { type: "string" },
            access: { type: "string" },
            type: { type: "string" },
          },
          required: ["id", "version", "name", "access", "type"],
        },
        IndicatorInfo: {
          type: "object",
          additionalProperties: false,
          properties: {
            id: {
              type: "string",
              description: "Indicator ID to use in /indicator endpoint",
            },
            name: {
              type: "string",
              description: "Human readable name",
            },
            description: {
              type: "string",
              description: "What this indicator does",
            },
            options: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  name: { type: "string" },
                  type: { type: "string" },
                  default: {},
                },
              },
              description: "Available options/inputs",
            },
          },
          required: ["id", "name", "description"],
        },
      },
      responses: {
        BadRequest: {
          description: "Bad Request",
          content: {
            "application/json": {
              schema: {
                $ref: "#/components/schemas/ErrorResponse",
              },
            },
          },
        },
        NotFound: {
          description: "Not Found",
          content: {
            "application/json": {
              schema: {
                $ref: "#/components/schemas/ErrorResponse",
              },
            },
          },
        },
        GatewayTimeout: {
          description: "Gateway Timeout",
          content: {
            "application/json": {
              schema: {
                $ref: "#/components/schemas/ErrorResponse",
              },
            },
          },
        },
        InternalError: {
          description: "Internal Server Error",
          content: {
            "application/json": {
              schema: {
                $ref: "#/components/schemas/ErrorResponse",
              },
            },
          },
        },
      },
    },
  };
}

const openapiDoc = buildOpenApiDoc();

fastify.get<{ Querystring: { symbol?: string } }>("/quote", async (request, reply) => {
  const { symbol } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: "Symbol is required" });
  }

  try {
    return await getQuote(symbol);
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({ error: errorMessage(err, "Failed to fetch quote") });
  }
});

fastify.get<{
  Querystring: {
    symbol?: string;
    timeframe?: string;
    range?: string;
    to?: string;
  };
}>("/history", async (request, reply) => {
  const { symbol, timeframe, range, to } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: "Symbol is required" });
  }

  try {
    const data = await getHistory({
      symbol,
      timeframe: asString(timeframe, "D"),
      range: asInt(range, 200),
      to: to ? asInt(to, 0) : undefined,
    });

    return {
      symbol,
      timeframe: asString(timeframe, "D"),
      range: asInt(range, 200),
      to: to ? asInt(to, 0) : undefined,
      candles: data,
    };
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(historyErrorStatus(err)).send({ error: errorMessage(err, "Failed to fetch history") });
  }
});

fastify.get<{
  Querystring: {
    q?: string;
    type?: string;
    offset?: string;
    limit?: string;
  };
}>("/v0/searchMarket", async (request, reply) => {
  const q = asString(request.query.q, "").trim();
  if (!q) {
    return reply.code(400).send({ error: "q is required" });
  }

  const type = request.query.type ? request.query.type.trim() : undefined;
  if (type && !MARKET_TYPES.has(type)) {
    return reply.code(400).send({
      error: `type must be one of: ${Array.from(MARKET_TYPES).join(", ")}`,
    });
  }

  const offset = asInt(request.query.offset, 0);
  if (offset < 0) {
    return reply.code(400).send({ error: "offset must be >= 0" });
  }

  const limit = asInt(request.query.limit, 10);
  if (limit < 1) {
    return reply.code(400).send({ error: "limit must be >= 1" });
  }

  const boundedLimit = Math.min(limit, 50);

  try {
    const results = await searchMarkets({
      query: q,
      type: type as any,
      offset,
    });

    const sliced = results.slice(0, boundedLimit);

    return {
      query: q,
      type: type ?? null,
      offset,
      limit: boundedLimit,
      count: sliced.length,
      results: sliced,
    };
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({ error: errorMessage(err, "Failed to search markets") });
  }
});

fastify.get<{
  Querystring: {
    symbol?: string;
    timeframe?: string;
    range?: string;
    to?: string;
    indicatorId?: string;
    options?: string;
  };
}>("/indicator", async (request, reply) => {
  const { symbol, timeframe, range, to, indicatorId, options } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: "Symbol is required" });
  }

  if (!indicatorId) {
    return reply.code(400).send({ error: "indicatorId is required" });
  }

  let parsedOptions: Record<string, unknown> | undefined;
  if (options) {
    try {
      parsedOptions = JSON.parse(options) as Record<string, unknown>;
    } catch {
      return reply.code(400).send({ error: "options must be valid JSON" });
    }
  }

  try {
    return await getIndicator({
      symbol,
      timeframe: asString(timeframe, "D"),
      range: asInt(range, 200),
      to: to ? asInt(to, 0) : undefined,
      indicatorId,
      options: parsedOptions,
    });
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({ error: errorMessage(err, "Failed to fetch indicator") });
  }
});

fastify.get<{ Querystring: { symbol?: string } }>("/ta", async (request, reply) => {
  const { symbol } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: "Symbol is required" });
  }

  try {
    return await getTechnicalAnalysis(symbol);
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({
      error: errorMessage(err, "Failed to fetch technical analysis"),
    });
  }
});

fastify.get("/indicators/private", async (request, reply) => {
  try {
    return await getPrivateIndicators();
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({
      error: errorMessage(err, "Failed to fetch private indicators"),
    });
  }
});

// Static indicator catalog
const INDICATOR_CATALOG = {
  standard: [
    {
      id: "STD;SMA",
      name: "Simple Moving Average",
      description: "简单移动平均线",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;EMA",
      name: "Exponential Moving Average",
      description: "指数移动平均线",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;WMA",
      name: "Weighted Moving Average",
      description: "加权移动平均线",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;VWMA",
      name: "Volume Weighted Moving Average",
      description: "成交量加权移动平均线",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;RSI",
      name: "Relative Strength Index",
      description: "相对强弱指标",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;MACD",
      name: "MACD",
      description: "指数平滑异同移动平均线",
      options: [
        { name: "fast_length", type: "integer", default: 12 },
        { name: "slow_length", type: "integer", default: 26 },
        { name: "signal_length", type: "integer", default: 9 },
      ],
    },
    {
      id: "STD;Stochastic",
      name: "Stochastic",
      description: "KDJ 随机指标",
      options: [
        { name: "K", type: "integer", default: 14 },
        { name: "D", type: "integer", default: 3 },
      ],
    },
    {
      id: "STD;Stoch_RSI",
      name: "Stochastic RSI",
      description: "随机相对强弱指标",
      options: [
        { name: "lengthRSI", type: "integer", default: 14 },
        { name: "lengthStoch", type: "integer", default: 14 },
      ],
    },
    {
      id: "STD;Bollinger_Bands",
      name: "Bollinger Bands",
      description: "布林带",
      options: [
        { name: "length", type: "integer", default: 20 },
        { name: "mult", type: "float", default: 2.0 },
      ],
    },
    {
      id: "STD;ATR",
      name: "Average True Range",
      description: "真实波幅均值",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;ADX",
      name: "Average Directional Index",
      description: "平均趋向指标",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;CCI",
      name: "Commodity Channel Index",
      description: "商品通道指标",
      options: [{ name: "length", type: "integer", default: 20 }],
    },
    {
      id: "STD;MOM",
      name: "Momentum",
      description: "动量指标",
      options: [{ name: "length", type: "integer", default: 10 }],
    },
    {
      id: "STD;ROC",
      name: "Rate of Change",
      description: "变动率指标",
      options: [{ name: "length", type: "integer", default: 9 }],
    },
    {
      id: "STD;OBV",
      name: "On Balance Volume",
      description: "能量潮指标",
      options: [],
    },
    {
      id: "STD;MFI",
      name: "Money Flow Index",
      description: "资金流量指标",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;VWAP",
      name: "VWAP",
      description: "成交量加权平均价格",
      options: [],
    },
    {
      id: "STD;Ichimoku",
      name: "Ichimoku Cloud",
      description: "一目均衡表 (云图)",
      options: [
        { name: "conversionPeriods", type: "integer", default: 9 },
        { name: "basePeriods", type: "integer", default: 26 },
      ],
    },
    {
      id: "STD;Pivot_Points_Standard",
      name: "Pivot Points",
      description: "枢轴点",
      options: [{ name: "type", type: "string", default: "Traditional" }],
    },
    {
      id: "STD;PSAR",
      name: "Parabolic SAR",
      description: "抛物线转向指标",
      options: [
        { name: "start", type: "float", default: 0.02 },
        { name: "inc", type: "float", default: 0.02 },
        { name: "max", type: "float", default: 0.2 },
      ],
    },
    {
      id: "STD;Williams_R",
      name: "Williams %R",
      description: "威廉指标",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;Aroon",
      name: "Aroon",
      description: "阿隆指标",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;DMI",
      name: "Directional Movement Index",
      description: "趋向指标",
      options: [{ name: "length", type: "integer", default: 14 }],
    },
    {
      id: "STD;TRIX",
      name: "TRIX",
      description: "三重指数平滑移动平均",
      options: [{ name: "length", type: "integer", default: 18 }],
    },
    {
      id: "STD;CMF",
      name: "Chaikin Money Flow",
      description: "蔡金资金流量",
      options: [{ name: "length", type: "integer", default: 20 }],
    },
    {
      id: "STD;Chaikin_Osc",
      name: "Chaikin Oscillator",
      description: "蔡金震荡指标",
      options: [],
    },
    {
      id: "STD;Keltner_Channels",
      name: "Keltner Channels",
      description: "肯特纳通道",
      options: [
        { name: "length", type: "integer", default: 20 },
        { name: "mult", type: "float", default: 2.0 },
      ],
    },
    {
      id: "STD;Donchian_Channels",
      name: "Donchian Channels",
      description: "唐奇安通道",
      options: [{ name: "length", type: "integer", default: 20 }],
    },
    {
      id: "STD;HV",
      name: "Historical Volatility",
      description: "历史波动率",
      options: [{ name: "length", type: "integer", default: 10 }],
    },
    {
      id: "STD;MACD_Histogram",
      name: "MACD Histogram",
      description: "MACD 柱状图",
      options: [],
    },
  ],
  builtin: [
    {
      id: "Volume@tv-basicstudies-241",
      name: "Volume",
      description: "成交量",
      options: [],
    },
    {
      id: "VbPFixed@tv-volumebyprice-53!",
      name: "Volume Profile Fixed Range",
      description: "固定范围成交量分布",
      options: [{ name: "rows", type: "integer", default: 24 }],
    },
    {
      id: "VbPSessions@tv-volumebyprice-53",
      name: "Volume Profile Sessions",
      description: "分时成交量分布",
      options: [],
    },
    {
      id: "VbPVisible@tv-volumebyprice-53",
      name: "Volume Profile Visible Range",
      description: "可视范围成交量分布",
      options: [],
    },
  ],
};

fastify.get("/indicators", async () => {
  return INDICATOR_CATALOG;
});

fastify.get("/openapi.json", async (_request, reply) => {
  return reply.header("content-type", "application/json; charset=utf-8").send(openapiDoc);
});

fastify.get("/health", async () => {
  return { status: "ok" };
});

const start = async () => {
  try {
    await fastify.listen({ port: PORT, host: "0.0.0.0" });
    console.log(`Stock API running on port ${PORT}`);
  } catch (err: unknown) {
    fastify.log.error(err);
    process.exit(1);
  }
};

start();
