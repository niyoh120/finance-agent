import "dotenv/config";
import path from "path";
import { fileURLToPath } from "url";
import { TradingViewService } from "./service.js";
import type { Config } from "./types.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadConfig(): Config {
  const symbolsEnv = process.env.TV_SYMBOLS || "NASDAQ:AAPL,NASDAQ:GOOGL";
  const symbols = symbolsEnv.split(",").map((s) => s.trim());

  return {
    symbols,
    timeframe: process.env.TV_TIMEFRAME || "1",
    tradingviewSession: process.env.TV_SESSION,
    tradingviewSignature: process.env.TV_SIGNATURE,
    databasePath:
      process.env.TV_DATABASE_PATH ||
      path.join(__dirname, "..", "..", "data", "stock_prices.db"),
  };
}

async function main(): Promise<void> {
  const config = loadConfig();

  console.log("=== TradingView Stock Price Service ===");
  console.log(`Symbols: ${config.symbols.join(", ")}`);
  console.log(`Timeframe: ${config.timeframe} minute(s)`);
  console.log(`Database: ${config.databasePath}`);
  console.log("");

  const service = new TradingViewService(config);

  process.on("SIGINT", () => {
    console.log("\nReceived SIGINT, shutting down...");
    service.stop();
    process.exit(0);
  });

  process.on("SIGTERM", () => {
    console.log("\nReceived SIGTERM, shutting down...");
    service.stop();
    process.exit(0);
  });

  await service.start();
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
