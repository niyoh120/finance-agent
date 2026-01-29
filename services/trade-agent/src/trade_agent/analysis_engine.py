from __future__ import annotations

import inspect
import logging
import os
from datetime import datetime, timezone

from agno.db.sqlite import SqliteDb
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

from .agents import (
    RiskManager,
    build_fundamental_analyst,
    build_options_flow_analyst,
    build_portfolio_manager,
    build_sentiment_analyst,
    build_technical_analyst,
    build_wyckoff_analyst,
)
from .config import AppConfig
from .models import (
    DecisionDraft,
    FundamentalSignal,
    OptionsFlowSignal,
    RiskLimits,
    SentimentSignal,
    TechnicalSignal,
    TradingDecision,
    WyckoffSignal,
)
from .tools import fetch_stock_history

logger = logging.getLogger(__name__)


def build_analysis_workflow(config: AppConfig) -> Workflow:
    db = SqliteDb(
        db_file=config.storage.sqlite_db_path,
        session_table="analysis_workflow_session",
    )
    technical = build_technical_analyst(config)
    options = build_options_flow_analyst(config)
    sentiment = build_sentiment_analyst(config)
    fundamental = build_fundamental_analyst(config)
    wyckoff = build_wyckoff_analyst(config)
    risk_manager = RiskManager(config)
    portfolio_manager = build_portfolio_manager(config)

    def risk_step(step_input: StepInput) -> StepOutput:
        symbol = (step_input.input or "").strip().upper()
        candles = fetch_stock_history(
            base_url=config.stock_api.url,
            symbol=symbol,
            timeframe=config.analysis.timeframe,
            range=config.analysis.history_range,
        )
        closes = [candle.close for candle in candles]
        hard_limits = risk_manager.calculate_hard_limits(closes)
        adjusted_limits = risk_manager.adjust_with_llm(
            hard_limits, f"ticker={symbol}, candles={len(candles)}"
        )
        return StepOutput(content=adjusted_limits)

    def decision_step(step_input: StepInput) -> StepOutput:
        symbol = (step_input.input or "").strip().upper()
        failed_analysts: list[str] = []

        technical_signal, failed = _coerce_step_with_status(
            step_input.get_step_content("technical"), TechnicalSignal, "技术分析师"
        )
        if failed:
            failed_analysts.append("技术分析师")

        options_signal, failed = _coerce_step_with_status(
            step_input.get_step_content("options"), OptionsFlowSignal, "期权流分析师"
        )
        if failed:
            failed_analysts.append("期权流分析师")

        sentiment_signal, failed = _coerce_step_with_status(
            step_input.get_step_content("sentiment"), SentimentSignal, "情绪分析师"
        )
        if failed:
            failed_analysts.append("情绪分析师")

        fundamental_signal, failed = _coerce_step_with_status(
            step_input.get_step_content("fundamental"),
            FundamentalSignal,
            "基本面分析师",
        )
        if failed:
            failed_analysts.append("基本面分析师")

        wyckoff_signal, failed = _coerce_step_with_status(
            step_input.get_step_content("wyckoff"), WyckoffSignal, "威科夫分析师"
        )
        if failed:
            failed_analysts.append("威科夫分析师")

        risk_limits = _coerce_step(
            step_input.get_step_content("risk_limits"), RiskLimits
        )

        # 构建 prompt，如有失败的分析师则提示
        failure_notice = ""
        if failed_analysts:
            failure_notice = (
                f"⚠️ 注意：以下分析师执行失败，其信号不可用：{', '.join(failed_analysts)}。\n"
                "请基于可用信号做出保守决策，并在 reasoning 中说明哪些信号缺失。\n\n"
            )

        prompt = (
            f"{failure_notice}"
            "请基于以下信号与风险约束做出决策:\n"
            f"技术面: {technical_signal}\n"
            f"期权流: {options_signal}\n"
            f"情绪: {sentiment_signal}\n"
            f"基本面: {fundamental_signal}\n"
            f"威科夫: {wyckoff_signal}\n"
            f"风险约束: {risk_limits}"
        )
        response = portfolio_manager.run(
            prompt, output_schema=DecisionDraft, stream=False
        )
        draft = _coerce_step(response.content, DecisionDraft)

        target_size = min(draft.target_position_size, risk_limits.max_position_size)
        decision = TradingDecision(
            ticker=symbol,
            timestamp=datetime.now(timezone.utc),
            action=draft.action,
            target_position_size=target_size,
            confidence=draft.confidence,
            signals={
                "technical": technical_signal.model_dump(),
                "options": options_signal.model_dump(),
                "sentiment": sentiment_signal.model_dump(),
                "fundamental": fundamental_signal.model_dump(),
                "wyckoff": wyckoff_signal.model_dump(),
            },
            risk_limits=risk_limits,
            reasoning=draft.reasoning,
        )
        return StepOutput(content=decision)

    analysis_parallel = _build_parallel(
        Step(
            name="technical",
            description="技术面分析",
            agent=technical,
        ),
        Step(
            name="options",
            description="期权流分析",
            agent=options,
        ),
        Step(
            name="sentiment",
            description="新闻情绪分析",
            agent=sentiment,
        ),
        Step(
            name="fundamental",
            description="基本面分析",
            agent=fundamental,
        ),
        Step(
            name="wyckoff",
            description="威科夫分析",
            agent=wyckoff,
        ),
        Step(
            name="risk_limits",
            description="风险约束计算",
            executor=risk_step,
        ),
        name="analysis_parallel",
        description="并行分析阶段",
    )

    steps = [
        *analysis_parallel,
        Step(
            name="decision",
            description="组合决策",
            executor=decision_step,
        ),
    ]

    return Workflow(
        name="Trade Analysis Workflow",
        description="多智能体交易分析与决策工作流",
        db=db,
        steps=steps,
    )


class AnalysisEngine:
    def __init__(self, config: AppConfig) -> None:
        self._workflow = build_analysis_workflow(config)

    def run(self, ticker: str) -> TradingDecision:
        response = self._workflow.run(input=ticker, stream=False)
        content = getattr(response, "content", response)
        return _coerce_step(content, TradingDecision)


def _coerce_step(content, schema):
    result, _ = _coerce_step_with_status(content, schema)
    return result


def _coerce_step_with_status(content, schema, analyst_name: str | None = None):
    """
    转换 step 输出为指定 schema。

    Returns:
        tuple: (signal, failed) - signal 为解析后的对象，failed 为是否使用了默认值
    """
    if content is None:
        name = analyst_name or schema.__name__
        logger.warning(
            "分析师返回空结果，使用默认信号",
            extra={"schema": schema.__name__, "analyst": name},
        )
        return _create_default_signal(schema), True
    if isinstance(content, schema):
        return content, False
    if isinstance(content, str):
        try:
            return schema.model_validate_json(content), False
        except Exception:
            logger.warning(
                "Failed to parse JSON content", extra={"schema": schema.__name__}
            )
    if isinstance(content, dict):
        return schema.model_validate(content), False
    logger.warning("Unexpected step output type", extra={"type": type(content)})
    return schema.model_validate(content), False


_SIGNAL_DEFAULTS: dict = {
    "TechnicalSignal": {
        "signal": "neutral",
        "confidence": 0,
        "reasoning": "分析失败，无法获取技术面信号",
    },
    "OptionsFlowSignal": {
        "signal": "neutral",
        "confidence": 0,
        "reasoning": "分析失败，无法获取期权流信号",
    },
    "SentimentSignal": {
        "signal": "neutral",
        "confidence": 0,
        "sentiment_score": 0,
        "reasoning": "分析失败，无法获取情绪信号",
    },
    "FundamentalSignal": {
        "signal": "neutral",
        "confidence": 0,
        "valuation": "未知",
        "financial_health": "未知",
        "reasoning": "分析失败，无法获取基本面信号",
    },
    "WyckoffSignal": {
        "signal": "neutral",
        "confidence": 0,
        "reasoning": "分析失败，无法获取威科夫信号",
    },
    "RiskLimits": {
        "max_position_size": 0.0,
        "max_loss_per_trade": 0.0,
        "max_portfolio_volatility": 0.0,
        "notes": "风险计算失败，使用保守默认值",
    },
    "DecisionDraft": {
        "action": "HOLD",
        "target_position_size": 0.0,
        "confidence": 0,
        "reasoning": "决策生成失败，默认持有",
    },
}


def _create_default_signal(schema):
    """当分析师返回 None 时，创建默认的空信号对象"""
    schema_name = schema.__name__
    if schema_name in _SIGNAL_DEFAULTS:
        return schema.model_validate(_SIGNAL_DEFAULTS[schema_name])
    raise ValueError(f"No default defined for schema: {schema_name}")


def _build_parallel(*steps: Step, name: str, description: str) -> list[Parallel]:
    parallel_list = []
    for i in range(0, len(steps), 2):
        parallel_list.append(Parallel(steps[i], steps[i + 1]))
    return parallel_list
