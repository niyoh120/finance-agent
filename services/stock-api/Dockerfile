FROM node:24-alpine AS builder

WORKDIR /app/services/stock-api

COPY services/stock-api/package.json services/stock-api/package-lock.json ./
RUN npm ci

COPY services/stock-api/tsconfig.json ./
COPY services/stock-api/src ./src

RUN npm run build

FROM node:24-alpine

WORKDIR /app/services/stock-api

COPY services/stock-api/package.json services/stock-api/package-lock.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/services/stock-api/dist ./dist

EXPOSE 3000

CMD ["node", "dist/index.js"]
