"""
config.py – Centralised settings and domain constants.

Pydantic-settings reads values from .env (via python-dotenv) and from
environment variables (env vars take priority over .env).
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Optional API keys (agent works without any of these)
    ieee_api_key: str = Field(default="", description="IEEE Xplore API key")
    elsevier_api_key: str = Field(default="", description="Elsevier/Scopus API key")
    crossref_email: str = Field(
        default="research-agent@example.com",
        description="Email for CrossRef polite pool (improves rate limits)",
    )
    semantic_scholar_api_key: str = Field(
        default="", description="Semantic Scholar API key (raises rate limit)"
    )
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for text-embedding-3-small embeddings",
    )

    results_per_source: int = Field(default=25, ge=1, le=100)
    output_dir: Path = Field(default=Path("outputs"))

    # ── Neo4j (local install) ──────────────────────────────────────────────
    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j Bolt URI",
    )
    neo4j_user: str = Field(default="neo4j", description="Neo4j username")
    neo4j_password: str = Field(default="password", description="Neo4j password")

    # ── Qdrant (Docker: docker compose up -d qdrant) ───────────────────────
    qdrant_host: str = Field(default="localhost", description="Qdrant host")
    qdrant_port: int = Field(default=6333, description="Qdrant REST port")
    qdrant_collection: str = Field(
        default="manufacturing_research",
        description="Qdrant collection name for paper chunk embeddings",
    )

    # ── Knowledge-graph settings ───────────────────────────────────────────
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model name (text-embedding-3-small = 1536-dim)",
    )
    kg_chunk_words: int = Field(
        default=400,
        description="Words per text chunk before embedding",
    )
    kg_chunk_overlap: int = Field(
        default=50,
        description="Word overlap between consecutive chunks",
    )
    kb_dir: Path = Field(
        default=Path("knowledge_base"),
        description="Root directory for the local corpus (created by downloader.py)",
    )


# Module-level singleton – import this everywhere
settings = Settings()

# ---------------------------------------------------------------------------
# DOI prefixes for publisher-scoped CrossRef filtering
# ---------------------------------------------------------------------------
DOI_PREFIXES: Final[dict[str, str]] = {
    "IEEE":          "10.1109",
    "ScienceDirect": "10.1016",
    "TaylorFrancis": "10.1080",
    "MDPI":          "10.3390",
    "Springer":      "10.1007",   # Journal of Math in Industry, Lecture Notes, etc.
    "ACS":           "10.1021",   # Energy & Fuels, Ind. Eng. Chem. Research, etc.
    "Wiley":         "10.1002",   # AIChE Journal, Intl J Industrial Engineering, etc.
}

# Reverse map: DOI prefix → display source name
PREFIX_TO_SOURCE: Final[dict[str, str]] = {v: k for k, v in DOI_PREFIXES.items()}

# ---------------------------------------------------------------------------
# Manufacturing topic keywords (used for query expansion + filtering)
# ---------------------------------------------------------------------------
TOPIC_TERMS: Final[list[str]] = [
    "FMEA",
    "PFMEA",
    "failure mode effects analysis",
    "failure mode and effects analysis",
    "digital twin",
    "production optimization",
    "energy optimization",
    "energy efficiency",
    "ESG",
    "sustainability",
    "root cause analysis",
    "root-cause",
    "RCA",
    "ODR generation",
    "operational data report",
    "actionable insights",
    "data-driven modeling",
    "data driven modeling",
    "physics-based modeling",
    "physics-informed",
    "physics informed neural",
    "hybrid modeling",
    "predictive maintenance",
    "process optimization",
    "condition monitoring",
    "anomaly detection",
    "fault detection",
    "remaining useful life",
    "quality control",
    "six sigma",
    "lean manufacturing",
    # Rotary kiln / thermal process specific
    "ring formation",
    "ring detection",
    "rotary kiln",
    "shell temperature",
    "soft sensor",
    "heat transfer model",
    "deposit characterization",
    "lime kiln",
    "clinker",
    "back pressure",
    "CO content",
    "fouling",
    "scaling",
    "accretion",
    "build-up detection",
]

INDUSTRY_TERMS: Final[list[str]] = [
    "cement",
    "steel",
    "aluminium",
    "aluminum",
    "tyre",
    "tire",
    "oil and gas",
    "oil & gas",
    "petroleum",
    "refinery",
    "specialty chemicals",
    "speciality chemicals",
    "paper and pulp",
    "pulp and paper",
    "paper mill",
    "mining",
    "quarry",
    "automobile",
    "automotive",
    "manufacturing",
    "industrial",
    "process industry",
    "heavy industry",
    "chemical plant",
    "blast furnace",
    "kiln",
    "smelter",
    "foundry",
]

# ---------------------------------------------------------------------------
# Medium RSS tag slugs (medium.com/feed/tag/<slug>)
# ---------------------------------------------------------------------------
MEDIUM_TAGS: Final[list[str]] = [
    "manufacturing",
    "digital-twin",
    "predictive-maintenance",
    "industrial-iot",
    "iiot",
    "data-science",
    "machine-learning",
    "sustainability",
    "process-optimization",
    "energy-efficiency",
    "industry-4-0",
    "artificial-intelligence",
]

# ---------------------------------------------------------------------------
# Per-source async concurrency limits (asyncio.Semaphore values)
# ---------------------------------------------------------------------------
CONCURRENCY: Final[dict[str, int]] = {
    "crossref":         3,   # fires 7 parallel sub-requests (one per DOI prefix)
    "semantic_scholar": 1,   # 1 rps without API key
    "medium":           3,
    "slideshare":       2,
}

# HTTP timeout in seconds
TIMEOUT_SECONDS: Final[float] = 20.0
