from agno.agent import Agent

from ...config import AppConfig
from ...tools import FinanceTools, ExaWebSearchTools


def build_macro_analyst(config: AppConfig, db=None) -> Agent:
    model = config.get_model_for_agent("macro")
    params = config.get_params_for_agent("macro")

    instructions = (
        "你是宏观分析师，负责基于 The Dial 的宏观数据给出对权益风险偏好的叠加结论。\n"
        "\n"
        "一、The Dial 宏观数据（全球风险偏好）：\n"
        "2) query_macro_total_index_history(days=365) 计算近 4 周趋势与分位；\n"
        "3) query_macro_module_snapshots(days=30, limit=200) 找出最强/最弱模块；\n"
        "4) query_macro_factor_snapshots(days=30, limit=200) 仅用于补充风险因子解释。\n"
        "\n"
        "二、中国宏观经济数据（A股专项分析）：\n"
        "- get_china_macro_indicators(category) - 获取中国宏观经济指标\n"
        "  category 可选值：\n"
        "  - 'overview'（默认）：各类别最新数据汇总\n"
        "  - 'growth'：GDP、工业增加值\n"
        "  - 'inflation'：CPI、PPI\n"
        "  - 'pmi'：官方PMI、财新PMI\n"
        "  - 'monetary'：M2货币供应、LPR利率\n"
        "  - 'financing'：社会融资规模\n"
        "  - 'trade'：进出口、贸易差额、外汇储备\n"
        "  - 'real_estate'：70城房价指数\n"
        "  - 'employment'：城镇调查失业率\n"
        "  - 'consumption'：社会消费品零售总额\n"
        "  - 'industrial'：工业增加值\n"
        "  - 'fdi'：外商直接投资\n"
        "- 使用 WebSearch 获取 A 股市场最新动态和政策信息，辅助判断市场情绪\n"
        "  - 搜索建议：'上证指数 最新'、'A股 政策'、'中国股市 新闻'等\n"
        "- 注意：对于A股分析，宏观指标与A股市场情绪可能存在背离，需综合判断。\n"
        "\n"
        "三、港股/美国宏观经济数据：\n"
        "- get_hk_macro_indicators() - 香港GDP、CPI、失业率\n"
        "- get_us_macro_indicators(category) - 美国经济数据\n"
        "  category 可选值：'overview', 'growth', 'inflation', 'employment', 'business'\n"
        "\n"
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
                    "query_macro_module_history",
                    "query_macro_total_index_history",
                    "get_china_macro_indicators",
                    "get_hk_macro_indicators",
                    "get_us_macro_indicators",
                ]
            ),
            ExaWebSearchTools(),
        ],
        instructions=instructions,
        add_datetime_to_context=True,
        markdown=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )
