import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.run.workflow import WorkflowRunOutputEvent
from agno.workflow import Parallel, Step, StepInput, StepOutput, Workflow
from beartype.typing import Callable
from pydantic import BaseModel

from ..agents import (
    build_cn_fundamental_analyst,
    build_macro_analyst,
    build_options_flow_analyst,
    build_portfolio_manager,
    build_risk_manager,
    build_sentiment_analyst,
    build_technical_analyst,
    build_us_fundamental_analyst,
    build_wyckoff_analyst,
)
from ..config import AppConfig
from ..models import (
    DecisionDraft,
    FundamentalSignal,
    MacroSignal,
    OptionsFlowSignal,
    RiskLimits,
    SentimentSignal,
    TechnicalSignal,
    TradingDecision,
    WyckoffSignal,
)

logger = logging.getLogger(__name__)


class AnalysisStepConfig(BaseModel):
    name: str
    desc: str
    agent_builder: Callable[..., Agent]
    output_schema: Any


def build_parallel_analysis_step(config: AppConfig) -> Parallel:
    step_configs = [
        AnalysisStepConfig(
            name="technical",
            desc="技术分析",
            agent_builder=build_technical_analyst,
            output_schema=TechnicalSignal,
        ),
        AnalysisStepConfig(
            name="options",
            desc="期权分析",
            agent_builder=build_options_flow_analyst,
            output_schema=OptionsFlowSignal,
        ),
        AnalysisStepConfig(
            name="sentiment",
            desc="情绪分析",
            agent_builder=build_sentiment_analyst,
            output_schema=SentimentSignal,
        ),
        # Note: fundamental step handled separately with market-based routing
        # See custom executor below
        AnalysisStepConfig(
            name="macro",
            desc="宏观分析",
            agent_builder=build_macro_analyst,
            output_schema=MacroSignal,
        ),
        AnalysisStepConfig(
            name="wyckoff",
            desc="Wyckoff分析",
            agent_builder=build_wyckoff_analyst,
            output_schema=WyckoffSignal,
        ),
        AnalysisStepConfig(
            name="risk_limits",
            desc="风险控制",
            agent_builder=build_risk_manager,
            output_schema=RiskLimits,
        ),
    ]

    sem = asyncio.Semaphore(config.analysis.parallel_num)

    def is_cn_market(ticker: str) -> bool:
        """检测是否为A股或港股代码

        A股: 6位纯数字 (如 '600519', '000001')
        港股: 数字.HK格式 (如 '0700.HK', '3690.HK')
        """
        import re

        # A股: 6位数字
        if re.match(r"^\d{6}$", ticker):
            return True
        # 港股: 数字.HK
        if re.match(r"^\d+\.HK$", ticker, re.IGNORECASE):
            return True
        return False

    steps = []

    def make_executor(step_config: AnalysisStepConfig):
        async def executor(
            step_input: StepInput,
        ) -> AsyncIterator[WorkflowRunOutputEvent | StepOutput]:
            async with sem:
                agent = step_config.agent_builder(config, db=InMemoryDb())
                response_iter = agent.arun(
                    input=str(step_input.input),
                    stream=True,
                    stream_events=True,
                    output_schema=step_config.output_schema,
                )
                async for event in response_iter:
                    yield event
                response = agent.get_last_run_output()
                assert response is not None
                yield StepOutput(content=response.content)

        return executor

    # 添加标准步骤
    for step_config in step_configs:
        steps.append(
            Step(
                name=step_config.name,
                description=step_config.desc,
                executor=make_executor(step_config),
            )
        )

    # 添加基本面分析步骤（带市场路由）
    async def fundamental_executor(
        step_input: StepInput,
    ) -> AsyncIterator[WorkflowRunOutputEvent | StepOutput]:
        async with sem:
            # 从输入中提取 ticker
            input_str = str(step_input.input)
            # 简单提取第一个看起来像代码的部分
            import re

            ticker_match = re.search(r"\b[A-Z0-9]+(?:\.HK)?\b", input_str, re.IGNORECASE)
            ticker = ticker_match.group(0) if ticker_match else ""

            # 根据市场选择分析师
            if is_cn_market(ticker):
                agent = build_cn_fundamental_analyst(config, db=InMemoryDb())
                logger.info(f"Using CN fundamental analyst for {ticker}")
            else:
                agent = build_us_fundamental_analyst(config, db=InMemoryDb())
                logger.info(f"Using US fundamental analyst for {ticker}")

            response_iter = agent.arun(
                input=input_str,
                stream=True,
                stream_events=True,
                output_schema=FundamentalSignal,
            )
            async for event in response_iter:
                yield event
            response = agent.get_last_run_output()
            assert response is not None
            yield StepOutput(content=response.content)

    steps.append(
        Step(
            name="fundamental",
            description="基本面分析",
            executor=fundamental_executor,
        )
    )

    return Parallel(*steps, name="parallel_analysis", description="并行分析阶段")


def build_analysis_workflow(config: AppConfig) -> Workflow:
    db = SqliteDb(
        db_file=config.storage.sqlite_db_path,
        session_table="analysis_workflow_session",
    )
    portfolio_manager = build_portfolio_manager(config)

    async def decision_step(step_input: StepInput) -> StepOutput:
        technical_signal = step_input.get_step_content("technical")
        assert technical_signal

        options_signal = step_input.get_step_content("options")
        assert options_signal

        sentiment_signal = step_input.get_step_content("sentiment")
        assert sentiment_signal

        fundamental_signal = step_input.get_step_content("fundamental")
        assert fundamental_signal

        macro_signal = step_input.get_step_content("macro")
        assert macro_signal

        wyckoff_signal = step_input.get_step_content("wyckoff")
        assert wyckoff_signal

        risk_limits = step_input.get_step_content("risk_limits")
        assert risk_limits

        prompt = (
            "请基于以下信号与风险约束做出决策:\n"
            f"技术分析: {technical_signal}\n"
            f"期权分析: {options_signal}\n"
            f"情绪分析: {sentiment_signal}\n"
            f"基本面分析: {fundamental_signal}\n"
            f"宏观分析: {macro_signal}\n"
            f"威科夫分析: {wyckoff_signal}\n"
            f"风险控制 {risk_limits}"
        )
        response = await portfolio_manager.arun(input=prompt, stream=False, output_schema=DecisionDraft)
        draft = cast(DecisionDraft, response.content)

        decision = TradingDecision(
            ticker=draft.ticker,
            timestamp=datetime.now(UTC),
            action=draft.action,
            target_position_size=draft.target_position_size,
            confidence=draft.confidence,
            signals={
                "technical": technical_signal,
                "options": options_signal,
                "sentiment": sentiment_signal,
                "fundamental": fundamental_signal,
                "macro": macro_signal,
                "wyckoff": wyckoff_signal,
            },
            risk_limits=risk_limits,  # type: ignore
            reasoning=draft.reasoning,
        )
        return StepOutput(content=decision)

    steps = [
        build_parallel_analysis_step(config),
        Step(name="decision", description="组合决策", executor=decision_step),
    ]

    return Workflow(
        name="Trade Analysis Workflow",
        description="多智能体交易分析与决策工作流",
        db=db,
        steps=steps,
        stream=True,
        stream_events=True,
        stream_executor_events=True,
    )
