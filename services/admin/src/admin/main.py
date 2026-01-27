import logging
import os

import uvicorn
from fastapi import FastAPI
from shared.database import get_engine
from shared.logging import configure_logging
from shared.models.macro import (
    MacroFactorSnapshot,
    MacroModuleHistory,
    MacroModuleSnapshot,
    MacroReport,
    MacroTotalIndexHistory,
)
from shared.models.news import NewsArticle
from shared.models.options import OptionsFlow
from shared.models.stocks import StockPrice
from sqladmin import Admin, ModelView

configure_logging(service="admin")
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


class NewsArticleAdmin(ModelView, model=NewsArticle):
    column_list = [
        NewsArticle.id,
        NewsArticle.published_at,
        NewsArticle.type,
        NewsArticle.title,
        NewsArticle.author,
        NewsArticle.symbols,
        NewsArticle.importance,
        NewsArticle.url,
    ]

    column_searchable_list = [
        NewsArticle.external_id,
        NewsArticle.type,
        NewsArticle.title,
        NewsArticle.content,
        NewsArticle.author,
    ]
    column_sortable_list = [
        NewsArticle.published_at,
        NewsArticle.type,
        NewsArticle.importance,
    ]
    column_default_sort = [(NewsArticle.published_at, True)]

    column_labels = {
        NewsArticle.external_id: "外部ID",
        NewsArticle.type: "类型",
        NewsArticle.title: "标题",
        NewsArticle.content: "内容",
        NewsArticle.original_content: "原始内容",
        NewsArticle.url: "链接",
        NewsArticle.author: "作者",
        NewsArticle.symbols: "标的",
        NewsArticle.tags: "标签",
        NewsArticle.importance: "重要性",
        NewsArticle.published_at: "发布时间",
        NewsArticle.created_at: "入库时间",
    }

    form_excluded_columns = [NewsArticle.created_at]

    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True

    name = "新闻"
    name_plural = "新闻"
    icon = "fa-regular fa-newspaper"


class MacroReportAdmin(ModelView, model=MacroReport):
    column_list = [
        MacroReport.id,
        MacroReport.report_date,
        MacroReport.current_snapshot_date,
        MacroReport.compare_date,
        MacroReport.current_score,
        MacroReport.compare_score,
        MacroReport.change,
        MacroReport.change_pct,
        MacroReport.generated_at,
    ]

    column_sortable_list = [MacroReport.report_date, MacroReport.generated_at]
    column_default_sort = [(MacroReport.report_date, True)]

    column_labels = {
        MacroReport.report_date: "报告日期",
        MacroReport.current_snapshot_date: "快照日期",
        MacroReport.compare_date: "对比日期",
        MacroReport.current_score: "当前得分",
        MacroReport.compare_score: "对比得分",
        MacroReport.change: "变化",
        MacroReport.change_pct: "变化%",
        MacroReport.generated_at: "生成时间",
        MacroReport.created_at: "入库时间",
    }

    form_excluded_columns = [MacroReport.created_at]

    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True

    name = "宏观报告"
    name_plural = "宏观报告"
    icon = "fa-solid fa-chart-line"


class MacroModuleSnapshotAdmin(ModelView, model=MacroModuleSnapshot):
    column_list = [
        MacroModuleSnapshot.id,
        MacroModuleSnapshot.report_date,
        MacroModuleSnapshot.module_id,
        MacroModuleSnapshot.name,
        MacroModuleSnapshot.current_score,
        MacroModuleSnapshot.compare_score,
        MacroModuleSnapshot.change,
        MacroModuleSnapshot.change_pct,
    ]

    column_searchable_list = [
        MacroModuleSnapshot.module_id,
        MacroModuleSnapshot.name,
    ]
    column_sortable_list = [
        MacroModuleSnapshot.report_date,
        MacroModuleSnapshot.module_id,
        MacroModuleSnapshot.current_score,
    ]
    column_default_sort = [(MacroModuleSnapshot.report_date, True)]

    column_labels = {
        MacroModuleSnapshot.report_date: "报告日期",
        MacroModuleSnapshot.module_id: "模块ID",
        MacroModuleSnapshot.name: "模块名称",
        MacroModuleSnapshot.name_cn: "模块名称(中文)",
        MacroModuleSnapshot.current_score: "当前得分",
        MacroModuleSnapshot.compare_score: "对比得分",
        MacroModuleSnapshot.change: "变化",
        MacroModuleSnapshot.change_pct: "变化%",
        MacroModuleSnapshot.created_at: "入库时间",
    }

    form_excluded_columns = [MacroModuleSnapshot.created_at]

    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True

    name = "宏观模块快照"
    name_plural = "宏观模块快照"
    icon = "fa-solid fa-chart-area"


class MacroFactorSnapshotAdmin(ModelView, model=MacroFactorSnapshot):
    column_list = [
        MacroFactorSnapshot.id,
        MacroFactorSnapshot.report_date,
        MacroFactorSnapshot.module_id,
        MacroFactorSnapshot.factor_id,
        MacroFactorSnapshot.name,
        MacroFactorSnapshot.current_value,
        MacroFactorSnapshot.current_percentile,
        MacroFactorSnapshot.color,
        MacroFactorSnapshot.display_only,
    ]

    column_searchable_list = [
        MacroFactorSnapshot.module_id,
        MacroFactorSnapshot.factor_id,
        MacroFactorSnapshot.name,
    ]
    column_sortable_list = [
        MacroFactorSnapshot.report_date,
        MacroFactorSnapshot.module_id,
        MacroFactorSnapshot.factor_id,
    ]
    column_default_sort = [(MacroFactorSnapshot.report_date, True)]

    column_labels = {
        MacroFactorSnapshot.report_date: "报告日期",
        MacroFactorSnapshot.module_id: "模块ID",
        MacroFactorSnapshot.module_name: "模块名称",
        MacroFactorSnapshot.module_name_cn: "模块名称(中文)",
        MacroFactorSnapshot.factor_id: "因子ID",
        MacroFactorSnapshot.name: "因子名称",
        MacroFactorSnapshot.name_cn: "因子名称(中文)",
        MacroFactorSnapshot.current_value: "当前值",
        MacroFactorSnapshot.current_value_formatted: "当前值(格式化)",
        MacroFactorSnapshot.current_percentile: "当前分位",
        MacroFactorSnapshot.compare_value: "对比值",
        MacroFactorSnapshot.compare_value_formatted: "对比值(格式化)",
        MacroFactorSnapshot.compare_percentile: "对比分位",
        MacroFactorSnapshot.value_change: "值变化",
        MacroFactorSnapshot.value_change_pct: "值变化%",
        MacroFactorSnapshot.percentile_change: "分位变化",
        MacroFactorSnapshot.percentile_change_pct: "分位变化%",
        MacroFactorSnapshot.color: "颜色",
        MacroFactorSnapshot.display_only: "仅展示",
        MacroFactorSnapshot.created_at: "入库时间",
    }

    form_excluded_columns = [MacroFactorSnapshot.created_at]

    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True

    name = "宏观因子快照"
    name_plural = "宏观因子快照"
    icon = "fa-solid fa-filter"


class MacroModuleHistoryAdmin(ModelView, model=MacroModuleHistory):
    column_list = [
        MacroModuleHistory.id,
        MacroModuleHistory.date,
        MacroModuleHistory.module_id,
        MacroModuleHistory.module_name,
        MacroModuleHistory.value,
        MacroModuleHistory.percentile,
    ]

    column_searchable_list = [
        MacroModuleHistory.module_id,
        MacroModuleHistory.module_name,
    ]
    column_sortable_list = [
        MacroModuleHistory.date,
        MacroModuleHistory.module_id,
        MacroModuleHistory.value,
    ]
    column_default_sort = [(MacroModuleHistory.date, True)]

    column_labels = {
        MacroModuleHistory.date: "日期",
        MacroModuleHistory.module_id: "模块ID",
        MacroModuleHistory.module_name: "模块名称",
        MacroModuleHistory.module_name_cn: "模块名称(中文)",
        MacroModuleHistory.value: "值",
        MacroModuleHistory.percentile: "分位",
        MacroModuleHistory.created_at: "入库时间",
    }

    form_excluded_columns = [MacroModuleHistory.created_at]

    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True

    name = "宏观模块历史"
    name_plural = "宏观模块历史"
    icon = "fa-solid fa-clock-rotate-left"


class MacroTotalIndexHistoryAdmin(ModelView, model=MacroTotalIndexHistory):
    column_list = [
        MacroTotalIndexHistory.id,
        MacroTotalIndexHistory.date,
        MacroTotalIndexHistory.value,
        MacroTotalIndexHistory.percentile,
    ]

    column_sortable_list = [
        MacroTotalIndexHistory.date,
        MacroTotalIndexHistory.value,
    ]
    column_default_sort = [(MacroTotalIndexHistory.date, True)]

    column_labels = {
        MacroTotalIndexHistory.date: "日期",
        MacroTotalIndexHistory.value: "总指数",
        MacroTotalIndexHistory.percentile: "分位",
        MacroTotalIndexHistory.created_at: "入库时间",
    }

    form_excluded_columns = [MacroTotalIndexHistory.created_at]

    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True

    name = "宏观总指数历史"
    name_plural = "宏观总指数历史"
    icon = "fa-solid fa-wave-square"


def create_app() -> FastAPI:
    engine = get_engine()

    # If the service is mounted below a path prefix (e.g. https://example.com/admin),
    # set FA_ADMIN_ROOT_PATH=/admin so url generation includes the prefix.
    root_path = os.getenv("FA_ADMIN_ROOT_PATH", "")
    app = FastAPI(root_path=root_path) if root_path else FastAPI()

    admin = Admin(app, engine, title="Finance Admin")
    admin.add_view(OptionsFlowAdmin)
    admin.add_view(StockPriceAdmin)
    admin.add_view(NewsArticleAdmin)
    admin.add_view(MacroReportAdmin)
    admin.add_view(MacroModuleSnapshotAdmin)
    admin.add_view(MacroFactorSnapshotAdmin)
    admin.add_view(MacroModuleHistoryAdmin)
    admin.add_view(MacroTotalIndexHistoryAdmin)

    return app


def main():
    host = os.getenv("FA_ADMIN_HOST", "0.0.0.0")  # Use 0.0.0.0 for Docker
    port = int(os.getenv("FA_ADMIN_PORT", "8000"))

    app = create_app()

    # Prefer forwarded headers from a TLS-terminating reverse proxy.
    # Ensure your proxy passes `X-Forwarded-Proto: https`.
    forwarded_allow_ips = os.getenv("FA_ADMIN_FORWARDED_ALLOW_IPS")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
