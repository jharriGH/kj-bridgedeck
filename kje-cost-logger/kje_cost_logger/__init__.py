"""KJE empire-wide cost logger.

Usage (most common):

    from kje_cost_logger import CostLogger
    logger = CostLogger(
        bridgedeck_url=os.environ["BRIDGEDECK_URL"],
        api_key=os.environ["BRIDGEDECK_INGEST_KEY"],
        source_system="agentenginez",
        project_slug="agentenginez",
    )

    response = await anthropic.messages.create(model=..., ...)
    await logger.log_anthropic_call(response, model=..., intent="lead_qualify")

See docs/EMPIRE_COST_LOGGING_BUILD_CARD.md in kj-bridgedeck for the full
doctrine, recommended priority order, and pricing reference.
"""
from .client import CostLogger
from .pricing import (
    ANTHROPIC_PRICING,
    OPENAI_PRICING,
    calc_anthropic_cost,
    calc_openai_cost,
)
from .decorators import track_cost

__version__ = "1.0.0"

__all__ = [
    "CostLogger",
    "ANTHROPIC_PRICING",
    "OPENAI_PRICING",
    "calc_anthropic_cost",
    "calc_openai_cost",
    "track_cost",
    "__version__",
]
