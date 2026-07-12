# backend/app/agents/market.py
"""Market Intelligence node: GDELT kinetic-event volume + EIA/Alpha Vantage
price read (app/ingestion/gdelt.py, app/ingestion/prices.py -- this repo's
actual combined EIA+AlphaVantage module; docs/03's original table names them
as separate eia.py/alphavantage.py files, which were built combined instead).
The LLM only classifies/narrates -- x_kinetic and brent_price_usd_bbl are
passed through from the connectors verbatim.
"""
import httpx

from app.agents.llm_client import LLMClient
from app.agents.state import AgentState
from app.ingestion.gdelt import fetch_kinetic_volume
from app.ingestion.prices import PriceService

MARKET_SYSTEM_PROMPT = (
    "You are a market intelligence analyst for a crude oil procurement desk. "
    "You are given a GDELT kinetic-event volume reading (0-1, min-max scaled "
    "news-volume signal for corridor-related conflict/sanction/strike coverage) "
    "and a live Brent price. Classify geopolitical volatility as LOW, MEDIUM, "
    "or HIGH, and state whether these readings suggest a price spike. Never "
    "invent a different number than the one given -- cite the reading you were given.\n\n"
    "Respond with exactly two lines:\n"
    "CLASSIFICATION: <LOW|MEDIUM|HIGH> | <true|false>\n"
    "NARRATION: <2-3 sentence narration>"
)


def _parse_classification(text: str) -> tuple[str, bool]:
    for line in text.splitlines():
        if line.startswith("CLASSIFICATION:"):
            rest = line.removeprefix("CLASSIFICATION:").strip()
            parts = [p.strip() for p in rest.split("|")]
            label = parts[0].upper() if parts and parts[0].upper() in {"LOW", "MEDIUM", "HIGH"} else "MEDIUM"
            spike = len(parts) > 1 and parts[1].lower() == "true"
            return label, spike
    return "MEDIUM", False


async def run_market_node(
    state: AgentState,
    http_client: httpx.AsyncClient,
    price_service: PriceService,
    llm: LLMClient,
) -> AgentState:
    corridor = state["corridor"]
    x_kinetic = await fetch_kinetic_volume(http_client, corridor=corridor)
    brent_price = await price_service.get_brent_price(http_client)

    narration = await llm.narrate(
        MARKET_SYSTEM_PROMPT,
        f"GDELT kinetic-event volume for {corridor}: {x_kinetic:.3f} (0=quiet, 1=peak).\n"
        f"Live Brent price: ${brent_price:.2f}/bbl.",
    )
    label, spike = _parse_classification(narration) if llm.has_key else ("STUB", False)

    return {
        **state,
        "x_kinetic": x_kinetic,
        "brent_price_usd_bbl": brent_price,
        "market_volatility_label": label,
        "price_spike_detected": spike,
        "market_narration": narration,
    }
