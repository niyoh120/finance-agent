import logging
import os

import uvicorn
from dotenv import load_dotenv
from sqladmin import Admin, ModelView
from starlette.applications import Starlette

from shared.models.options import OptionsFlow
from shared.models.stocks import StockPrice
from shared.database import get_engine

load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class OptionsFlowAdmin(ModelView, model=OptionsFlow):
    column_list = [
        OptionsFlow.id,
        OptionsFlow.timestamp,
        OptionsFlow.symbol,
        OptionsFlow.strike,
        OptionsFlow.option_type,
        OptionsFlow.side,
        OptionsFlow.premium,
        OptionsFlow.vol_oi,
        OptionsFlow.dte,
    ]

    column_searchable_list = [OptionsFlow.symbol, OptionsFlow.message_id]
    column_sortable_list = [
        OptionsFlow.timestamp,
        OptionsFlow.symbol,
        OptionsFlow.premium,
        OptionsFlow.vol_oi,
        OptionsFlow.dte,
    ]
    column_default_sort = [(OptionsFlow.timestamp, True)]

    column_formatters = {
        OptionsFlow.premium: lambda m, a: f"${m.premium:,.0f}",
        OptionsFlow.vol_oi: lambda m, a: f"{m.vol_oi:.2f}",
        OptionsFlow.strike: lambda m, a: f"${m.strike:.2f}",
    }

    column_labels = {
        OptionsFlow.timestamp: "时间",
        OptionsFlow.symbol: "标的",
        OptionsFlow.strike: "行权价",
        OptionsFlow.option_type: "类型",
        OptionsFlow.side: "方向",
        OptionsFlow.premium: "权利金",
        OptionsFlow.vol_oi: "Vol/OI",
        OptionsFlow.dte: "DTE",
        OptionsFlow.interval_volume: "成交量",
        OptionsFlow.open_interest: "未平仓",
        OptionsFlow.otm_percent: "OTM%",
        OptionsFlow.bid_percent: "Bid%",
        OptionsFlow.ask_percent: "Ask%",
        OptionsFlow.avg_fill: "均价",
        OptionsFlow.multileg_percent: "多腿%",
        OptionsFlow.expiry: "到期日",
        OptionsFlow.raw_message: "原始消息",
    }

    form_excluded_columns = [OptionsFlow.created_at]

    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True

    name = "期权大单"
    name_plural = "期权大单"
    icon = "fa-solid fa-chart-line"


class StockPriceAdmin(ModelView, model=StockPrice):
    column_list = [
        StockPrice.id,
        StockPrice.timestamp,
        StockPrice.symbol,
        StockPrice.close,
        StockPrice.volume,
        StockPrice.timeframe,
    ]

    column_searchable_list = [StockPrice.symbol]
    column_sortable_list = [StockPrice.timestamp, StockPrice.symbol]
    column_default_sort = [(StockPrice.timestamp, True)]

    column_labels = {
        StockPrice.timestamp: "时间",
        StockPrice.symbol: "代码",
        StockPrice.close: "收盘价",
        StockPrice.volume: "成交量",
        StockPrice.timeframe: "周期",
    }

    name = "股价"
    name_plural = "股价"
    icon = "fa-solid fa-chart-bar"


def create_app() -> Starlette:
    engine = get_engine()

    app = Starlette()
    admin = Admin(app, engine, title="Finance Admin")
    admin.add_view(OptionsFlowAdmin)
    admin.add_view(StockPriceAdmin)

    return app


def main():
    host = os.getenv("ADMIN_HOST", "0.0.0.0")  # Use 0.0.0.0 for Docker
    port = int(os.getenv("ADMIN_PORT", "8000"))

    app = create_app()
    logger.info(f"Admin panel running at http://{host}:{port}/admin")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
