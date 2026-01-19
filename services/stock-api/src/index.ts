import Fastify from 'fastify';
import {
  getHistory,
  getIndicator,
  getPrivateIndicators,
  getQuote,
  getTechnicalAnalysis
} from './tv.js';

const fastify = Fastify({
  logger: true
});

const PORT = parseInt(process.env.PORT || '3000');

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

type OpenApiDoc = Record<string, unknown>;

function buildOpenApiDoc(): OpenApiDoc {
  return {
    openapi: '3.0.3',
    info: {
      title: 'stock-api',
      version: '1.0.0'
    },
    paths: {
      '/health': {
        get: {
          summary: 'Health check',
          responses: {
            200: {
              description: 'OK',
              content: {
                'application/json': {
                  schema: {
                    type: 'object',
                    additionalProperties: false,
                    properties: { status: { type: 'string' } },
                    required: ['status']
                  }
                }
              }
            }
          }
        }
      },
      '/quote': {
        get: {
          summary: 'Get realtime quote',
          parameters: [
            {
              name: 'symbol',
              in: 'query',
              required: true,
              schema: { type: 'string' },
              example: 'NASDAQ:AAPL'
            }
          ],
          responses: {
            200: {
              description: 'Quote',
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/QuoteData' }
                }
              }
            },
            400: { $ref: '#/components/responses/BadRequest' },
            500: { $ref: '#/components/responses/InternalError' }
          }
        }
      },
      '/history': {
        get: {
          summary: 'Get historical candles (OHLCV)',
          parameters: [
            { name: 'symbol', in: 'query', required: true, schema: { type: 'string' }, example: 'NASDAQ:AAPL' },
            { name: 'timeframe', in: 'query', required: false, schema: { type: 'string', default: 'D' }, example: 'D' },
            { name: 'range', in: 'query', required: false, schema: { type: 'integer', default: 200, minimum: 1 }, example: 200 },
            {
              name: 'to',
              in: 'query',
              required: false,
              schema: { type: 'integer', minimum: 1 },
              description: 'Unix time in seconds (end timestamp)',
              example: 1700000000
            }
          ],
          responses: {
            200: {
              description: 'Candles',
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/HistoryResponse' }
                }
              }
            },
            400: { $ref: '#/components/responses/BadRequest' },
            500: { $ref: '#/components/responses/InternalError' }
          }
        }
      },
      '/indicator': {
        get: {
          summary: 'Get indicator values',
          parameters: [
            { name: 'symbol', in: 'query', required: true, schema: { type: 'string' }, example: 'NASDAQ:AAPL' },
            { name: 'indicatorId', in: 'query', required: true, schema: { type: 'string' }, example: 'STD;EMA' },
            { name: 'timeframe', in: 'query', required: false, schema: { type: 'string', default: 'D' }, example: 'D' },
            { name: 'range', in: 'query', required: false, schema: { type: 'integer', default: 200, minimum: 1 }, example: 200 },
            {
              name: 'to',
              in: 'query',
              required: false,
              schema: { type: 'integer', minimum: 1 },
              description: 'Unix time in seconds (end timestamp)',
              example: 1700000000
            },
            {
              name: 'options',
              in: 'query',
              required: false,
              schema: { type: 'string' },
              description: 'JSON string of indicator options (inputs)'
            }
          ],
          responses: {
            200: {
              description: 'Indicator result',
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/IndicatorResult' }
                }
              }
            },
            400: { $ref: '#/components/responses/BadRequest' },
            500: { $ref: '#/components/responses/InternalError' }
          }
        }
      },
      '/ta': {
        get: {
          summary: 'Get TradingView Technical Analysis summary',
          parameters: [
            { name: 'symbol', in: 'query', required: true, schema: { type: 'string' }, example: 'NASDAQ:AAPL' }
          ],
          responses: {
            200: {
              description: 'TA results by timeframe',
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/TechnicalAnalysis' }
                }
              }
            },
            400: { $ref: '#/components/responses/BadRequest' },
            500: { $ref: '#/components/responses/InternalError' }
          }
        }
      },
      '/indicators/private': {
        get: {
          summary: 'List private indicators for current account',
          responses: {
            200: {
              description: 'Private indicators',
              content: {
                'application/json': {
                  schema: {
                    type: 'array',
                    items: { $ref: '#/components/schemas/PrivateIndicator' }
                  }
                }
              }
            },
            500: { $ref: '#/components/responses/InternalError' }
          }
        }
      },
      '/openapi.json': {
        get: {
          summary: 'OpenAPI spec',
          responses: {
            200: {
              description: 'OpenAPI document',
              content: {
                'application/json': {
                  schema: { type: 'object' }
                }
              }
            }
          }
        }
      }
    },
    components: {
      schemas: {
        ErrorResponse: {
          type: 'object',
          additionalProperties: false,
          properties: { error: { type: 'string' } },
          required: ['error']
        },
        Candle: {
          type: 'object',
          additionalProperties: false,
          properties: {
            time: { type: 'integer' },
            timestamp: { type: 'integer' },
            open: { type: 'number' },
            high: { type: 'number' },
            low: { type: 'number' },
            close: { type: 'number' },
            volume: { type: 'number', nullable: true }
          },
          required: ['time', 'timestamp', 'open', 'high', 'low', 'close']
        },
        QuoteData: {
          type: 'object',
          additionalProperties: false,
          properties: {
            symbol: { type: 'string' },
            price: { type: 'number' },
            volume: { type: 'number' },
            change: { type: 'number' },
            changePercent: { type: 'number' },
            high: { type: 'number' },
            low: { type: 'number' },
            open: { type: 'number' },
            prevClose: { type: 'number' },
            bid: { type: 'number' },
            ask: { type: 'number' },
            status: { type: 'string' },
            timestamp: { type: 'integer' }
          },
          required: [
            'symbol',
            'price',
            'volume',
            'change',
            'changePercent',
            'high',
            'low',
            'open',
            'prevClose',
            'bid',
            'ask',
            'status',
            'timestamp'
          ]
        },
        HistoryResponse: {
          type: 'object',
          additionalProperties: false,
          properties: {
            symbol: { type: 'string' },
            timeframe: { type: 'string' },
            range: { type: 'integer' },
            to: { type: 'integer', nullable: true },
            candles: { type: 'array', items: { $ref: '#/components/schemas/Candle' } }
          },
          required: ['symbol', 'timeframe', 'range', 'candles']
        },
        TechnicalAnalysis: {
          type: 'object',
          additionalProperties: {
            type: 'object',
            additionalProperties: false,
            properties: {
              Other: { type: 'number' },
              All: { type: 'number' },
              MA: { type: 'number' }
            },
            required: ['Other', 'All', 'MA']
          }
        },
        IndicatorResult: {
          type: 'object',
          additionalProperties: false,
          properties: {
            symbol: { type: 'string' },
            timeframe: { type: 'string' },
            range: { type: 'integer' },
            indicatorId: { type: 'string' },
            candles: { type: 'array', items: { $ref: '#/components/schemas/Candle' } },
            periods: { type: 'array', items: { type: 'object', additionalProperties: true } },
            plots: { type: 'object', additionalProperties: { type: 'string' }, nullable: true },
            strategyReport: { type: 'object', additionalProperties: true, nullable: true },
            graphic: { type: 'object', additionalProperties: true, nullable: true }
          },
          required: ['symbol', 'timeframe', 'range', 'indicatorId', 'candles', 'periods']
        },
        PrivateIndicator: {
          type: 'object',
          additionalProperties: false,
          properties: {
            id: { type: 'string' },
            version: { type: 'string' },
            name: { type: 'string' },
            access: { type: 'string' },
            type: { type: 'string' }
          },
          required: ['id', 'version', 'name', 'access', 'type']
        }
      },
      responses: {
        BadRequest: {
          description: 'Bad Request',
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/ErrorResponse' }
            }
          }
        },
        InternalError: {
          description: 'Internal Server Error',
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/ErrorResponse' }
            }
          }
        }
      }
    }
  };
}

const openapiDoc = buildOpenApiDoc();

fastify.get<{ Querystring: { symbol?: string } }>('/quote', async (request, reply) => {
  const { symbol } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: 'Symbol is required' });
  }

  try {
    return await getQuote(symbol);
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({ error: errorMessage(err, 'Failed to fetch quote') });
  }
});

fastify.get<{
  Querystring: {
    symbol?: string;
    timeframe?: string;
    range?: string;
    to?: string;
  };
}>('/history', async (request, reply) => {
  const { symbol, timeframe, range, to } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: 'Symbol is required' });
  }

  try {
    const data = await getHistory({
      symbol,
      timeframe: asString(timeframe, 'D'),
      range: asInt(range, 200),
      to: to ? asInt(to, 0) : undefined
    });

    return {
      symbol,
      timeframe: asString(timeframe, 'D'),
      range: asInt(range, 200),
      to: to ? asInt(to, 0) : undefined,
      candles: data
    };
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({ error: errorMessage(err, 'Failed to fetch history') });
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
}>('/indicator', async (request, reply) => {
  const { symbol, timeframe, range, to, indicatorId, options } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: 'Symbol is required' });
  }

  if (!indicatorId) {
    return reply.code(400).send({ error: 'indicatorId is required' });
  }

  let parsedOptions: Record<string, unknown> | undefined;
  if (options) {
    try {
      parsedOptions = JSON.parse(options) as Record<string, unknown>;
    } catch {
      return reply.code(400).send({ error: 'options must be valid JSON' });
    }
  }

  try {
    return await getIndicator({
      symbol,
      timeframe: asString(timeframe, 'D'),
      range: asInt(range, 200),
      to: to ? asInt(to, 0) : undefined,
      indicatorId,
      options: parsedOptions
    });
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({ error: errorMessage(err, 'Failed to fetch indicator') });
  }
});

fastify.get<{ Querystring: { symbol?: string } }>('/ta', async (request, reply) => {
  const { symbol } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: 'Symbol is required' });
  }

  try {
    return await getTechnicalAnalysis(symbol);
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({ error: errorMessage(err, 'Failed to fetch technical analysis') });
  }
});

fastify.get('/indicators/private', async (request, reply) => {
  try {
    return await getPrivateIndicators();
  } catch (err: unknown) {
    request.log.error(err);
    return reply.code(500).send({ error: errorMessage(err, 'Failed to fetch private indicators') });
  }
});

fastify.get('/openapi.json', async (_request, reply) => {
  return reply
    .header('content-type', 'application/json; charset=utf-8')
    .send(openapiDoc);
});

fastify.get('/health', async () => {
  return { status: 'ok' };
});

const start = async () => {
  try {
    await fastify.listen({ port: PORT, host: '0.0.0.0' });
    console.log(`Stock API running on port ${PORT}`);
  } catch (err: unknown) {
    fastify.log.error(err);
    process.exit(1);
  }
};

start();
