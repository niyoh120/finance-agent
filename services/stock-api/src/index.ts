import Fastify from 'fastify';
import dotenv from 'dotenv';
import { getQuote } from './tv.js';

dotenv.config();

const fastify = Fastify({
  logger: true
});

const PORT = parseInt(process.env.PORT || '3000');

fastify.get<{ Querystring: { symbol?: string } }>('/quote', async (request, reply) => {
  const { symbol } = request.query;

  if (!symbol) {
    return reply.code(400).send({ error: 'Symbol is required' });
  }

  try {
    const data = await getQuote(symbol);
    return data;
  } catch (err: any) {
    request.log.error(err);
    return reply.code(500).send({ error: err.message || 'Failed to fetch quote' });
  }
});

fastify.get('/health', async () => {
  return { status: 'ok' };
});

const start = async () => {
  try {
    await fastify.listen({ port: PORT, host: '0.0.0.0' });
    console.log(`Stock API running on port ${PORT}`);
  } catch (err) {
    fastify.log.error(err);
    process.exit(1);
  }
};

start();
