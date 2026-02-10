from agno.agent import Agent

from ...config import AppConfig
from ...tools import FinanceTools


def build_macro_analyst(config: AppConfig, db=None) -> Agent:
    model = config.get_model_for_agent("macro")
    params = config.get_params_for_agent("macro")

    instructions = (
        "你是宏观分析师，负责基于 The Dial 的宏观数据给出对权益风险偏好的叠加结论。\n"
        "优先使用 MCP 工具获取宏观数据：\n"
        "1) query_macro_reports(limit=1) 获取最新报告日与总指数快照；\n"
        "2) query_macro_total_index_history(days=365) 计算近 4 周趋势与分位；\n"
        "3) query_macro_module_snapshots(days=30, limit=200) 找出最强/最弱模块；\n"
        "4) query_macro_factor_snapshots(days=30, limit=200) 仅用于补充风险因子解释。\n"
        "补充数据源：\n"
        "- 可使用 `cn_stock_get_news_data` 获取 A 股重要指数 (如 '000001' 上证指数) 或个股的新闻，辅助判断中国市场情绪。\n"
        "- `cn_stock_get_time_info` 可获取当前 A 股交易日信息。\n"
        "方向规则（仅用于宏观风险偏好叠加，不改变风险硬约束）：\n"
        "- P = total_index_percentile。\n"
        "- risk_off: P<=0.25 或 (P<=0.35 且近4周趋势恶化) -> signal=bearish。\n"
        "- risk_on:  P>=0.75 或 (P>=0.65 且近4周趋势改善) -> signal=bullish。\n"
        "- 其他情况 -> regime=mixed, signal=neutral。\n"
        "置信度随 |P-0.5| 增加；若因子颜色与方向一致可 +10，否则 -10。\n"
        "key_modules/key_factors 控制在 3-5 条，不要输出原始全量列表。\n"
        "如果数据缺失或工具返回空列表：必须输出 signal=neutral、regime=mixed、confidence<=35，"
        "并在 reasoning 中说明宏观数据不可用。\n"
        "使用中文回答。\n"
    )

    return Agent(
        name="Macro Analyst",
        model=model,
        tools=[
            FinanceTools(
                include_tools=[
                    "query_macro_reports",
                    "query_macro_module_snapshots",
                    "query_macro_factor_snapshots",
                    "query_macro_module_history",
                    "query_macro_total_index_history",
                    "cn_stock_get_news_data",
                    "cn_stock_get_time_info",
                ]
            )
        ],
        instructions=instructions,
        add_datetime_to_context=True,
        markdown=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )
