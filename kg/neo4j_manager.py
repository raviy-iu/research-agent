"""
kg/neo4j_manager.py – Async Neo4j driver, schema bootstrap, and all Cypher CRUD.

All raw Cypher lives here; the rest of the kg/ package only calls these methods.

Environment variables (loaded from .env via config.Settings):
    NEO4J_URI       bolt://localhost:7687
    NEO4J_USER      neo4j
    NEO4J_PASSWORD  password   (change this after first Neo4j login)
"""
from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from config import settings, TOPIC_TERMS, INDUSTRY_TERMS

logger = logging.getLogger(__name__)


class Neo4jManager:
    """
    Async wrapper around the Neo4j driver.

    Usage (async context manager):
        async with Neo4jManager() as neo4j:
            await neo4j.setup_schema()
            await neo4j.upsert_article(...)
    """

    def __init__(self) -> None:
        self._driver: AsyncDriver | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        await self._driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s", settings.neo4j_uri)

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None

    async def __aenter__(self) -> "Neo4jManager":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Schema Setup ──────────────────────────────────────────────────────────

    async def setup_schema(self) -> None:
        """
        Idempotently bootstrap constraints, indexes, Topic/Industry seed nodes,
        and pre-defined RELATED_TO edges.  Safe to call on every startup.
        """
        async with self._driver.session() as s:

            # Uniqueness constraints (also create backing B-tree indexes)
            for cql in [
                "CREATE CONSTRAINT article_id_unique IF NOT EXISTS FOR (a:Article) REQUIRE a.id IS UNIQUE",
                "CREATE CONSTRAINT author_name_unique IF NOT EXISTS FOR (au:Author) REQUIRE au.name IS UNIQUE",
                "CREATE CONSTRAINT publisher_name_unique IF NOT EXISTS FOR (p:Publisher) REQUIRE p.name IS UNIQUE",
                "CREATE CONSTRAINT topic_name_unique IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
                "CREATE CONSTRAINT industry_name_unique IF NOT EXISTS FOR (i:Industry) REQUIRE i.name IS UNIQUE",
                "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
            ]:
                await s.run(cql)

            # Additional indexes for fast filtering
            for cql in [
                "CREATE FULLTEXT INDEX article_fulltext IF NOT EXISTS FOR (a:Article) ON EACH [a.title, a.abstract]",
                "CREATE INDEX article_year IF NOT EXISTS FOR (a:Article) ON (a.year)",
                "CREATE INDEX article_source IF NOT EXISTS FOR (a:Article) ON (a.source)",
                "CREATE INDEX article_dl_status IF NOT EXISTS FOR (a:Article) ON (a.download_status)",
                "CREATE INDEX chunk_article_id IF NOT EXISTS FOR (c:Chunk) ON (c.article_id)",
            ]:
                await s.run(cql)

            # Seed Topic nodes from config.TOPIC_TERMS
            for term in TOPIC_TERMS:
                await s.run("MERGE (:Topic {name: $n})", n=term)

            # Seed Industry nodes from config.INDUSTRY_TERMS
            for term in INDUSTRY_TERMS:
                await s.run("MERGE (:Industry {name: $n})", n=term)

            # Pre-defined topic relationships (synonyms + logical groups)
            topic_edges: list[tuple[str, str]] = [
                ("FMEA", "PFMEA"),
                ("FMEA", "failure mode effects analysis"),
                ("FMEA", "failure mode and effects analysis"),
                ("predictive maintenance", "condition monitoring"),
                ("predictive maintenance", "fault detection"),
                ("predictive maintenance", "remaining useful life"),
                ("digital twin", "hybrid modeling"),
                ("digital twin", "data-driven modeling"),
                ("digital twin", "physics-informed"),
                ("digital twin", "physics-based modeling"),
                ("anomaly detection", "fault detection"),
                ("anomaly detection", "remaining useful life"),
                ("root cause analysis", "FMEA"),
                ("root cause analysis", "RCA"),
                ("energy optimization", "process optimization"),
                ("energy optimization", "energy efficiency"),
                ("energy optimization", "ESG"),
                ("rotary kiln", "ring formation"),
                ("rotary kiln", "shell temperature"),
                ("rotary kiln", "clinker"),
                ("rotary kiln", "lime kiln"),
                ("rotary kiln", "fouling"),
                ("rotary kiln", "scaling"),
                ("rotary kiln", "accretion"),
                ("quality control", "six sigma"),
                ("quality control", "anomaly detection"),
                ("soft sensor", "data-driven modeling"),
                ("soft sensor", "hybrid modeling"),
            ]
            for src, dst in topic_edges:
                await s.run(
                    "MERGE (a:Topic {name: $src}) "
                    "MERGE (b:Topic {name: $dst}) "
                    "MERGE (a)-[:RELATED_TO]->(b)",
                    src=src, dst=dst,
                )

            # Industry synonym relationships
            industry_edges: list[tuple[str, str]] = [
                ("aluminium", "aluminum"),
                ("tyre", "tire"),
                ("cement", "kiln"),
                ("oil and gas", "oil & gas"),
                ("oil and gas", "petroleum"),
                ("oil and gas", "refinery"),
                ("paper and pulp", "pulp and paper"),
                ("paper and pulp", "paper mill"),
                ("mining", "quarry"),
                ("automobile", "automotive"),
                ("specialty chemicals", "speciality chemicals"),
            ]
            for src, dst in industry_edges:
                await s.run(
                    "MERGE (a:Industry {name: $src}) "
                    "MERGE (b:Industry {name: $dst}) "
                    "MERGE (a)-[:RELATED_TO]->(b)",
                    src=src, dst=dst,
                )

        logger.info("Neo4j schema setup complete")

    # ── Article CRUD ──────────────────────────────────────────────────────────

    async def article_exists(self, article_id: str) -> bool:
        """Return True if an Article node with this id already exists."""
        async with self._driver.session() as s:
            result = await s.run(
                "MATCH (a:Article {id: $id}) RETURN count(a) AS n",
                id=article_id,
            )
            record = await result.single()
            return (record["n"] > 0) if record else False

    async def upsert_article(self, props: dict[str, Any]) -> None:
        """
        MERGE an Article node; update mutable fields on match.

        Required keys: id, title, doi, url, source, year, abstract,
                       download_status, has_pdf, has_fulltext, local_path
        """
        cql = """
        MERGE (a:Article {id: $id})
        ON CREATE SET
          a.title           = $title,
          a.doi             = $doi,
          a.url             = $url,
          a.source          = $source,
          a.year            = $year,
          a.abstract        = $abstract,
          a.download_status = $download_status,
          a.has_pdf         = $has_pdf,
          a.has_fulltext    = $has_fulltext,
          a.local_path      = $local_path,
          a.ingested_at     = datetime()
        ON MATCH SET
          a.download_status = $download_status,
          a.has_pdf         = $has_pdf,
          a.has_fulltext    = $has_fulltext,
          a.updated_at      = datetime()
        """
        async with self._driver.session() as s:
            await s.run(cql, **props)

    async def link_authors(self, article_id: str, authors: list[str]) -> None:
        async with self._driver.session() as s:
            for name in authors:
                if name and name.strip():
                    await s.run(
                        "MATCH (a:Article {id: $aid}) "
                        "MERGE (au:Author {name: $name}) "
                        "MERGE (a)-[:AUTHORED_BY]->(au)",
                        aid=article_id, name=name.strip(),
                    )

    async def link_publisher(self, article_id: str, publisher: str) -> None:
        if not publisher:
            return
        async with self._driver.session() as s:
            await s.run(
                "MATCH (a:Article {id: $aid}) "
                "MERGE (p:Publisher {name: $pub}) "
                "MERGE (a)-[:PUBLISHED_BY]->(p)",
                aid=article_id, pub=publisher,
            )

    async def link_topics(self, article_id: str, topics: list[str]) -> None:
        async with self._driver.session() as s:
            for t in topics:
                await s.run(
                    "MATCH (a:Article {id: $aid}) "
                    "MERGE (t:Topic {name: $name}) "
                    "MERGE (a)-[:COVERS_TOPIC]->(t)",
                    aid=article_id, name=t,
                )

    async def link_industries(self, article_id: str, industries: list[str]) -> None:
        async with self._driver.session() as s:
            for ind in industries:
                await s.run(
                    "MATCH (a:Article {id: $aid}) "
                    "MERGE (i:Industry {name: $name}) "
                    "MERGE (a)-[:RELEVANT_TO]->(i)",
                    aid=article_id, name=ind,
                )

    async def upsert_chunk(self, chunk: dict[str, Any]) -> None:
        """
        MERGE a Chunk node and link it to its parent Article.

        Required keys: id, text, chunk_index, article_id
        """
        cql = """
        MERGE (c:Chunk {id: $id})
        ON CREATE SET
          c.text        = $text,
          c.chunk_index = $chunk_index,
          c.article_id  = $article_id
        WITH c
        MATCH (a:Article {id: $article_id})
        MERGE (a)-[:HAS_CHUNK]->(c)
        """
        async with self._driver.session() as s:
            await s.run(cql, **chunk)

    # ── Search Queries ────────────────────────────────────────────────────────

    async def search_by_topics_industries(
        self,
        topics: list[str],
        industries: list[str],
        limit: int = 20,
    ) -> list[dict]:
        """
        Weighted graph traversal:
          - Direct topic match         -> weight 3
          - 1-hop RELATED_TO topic     -> weight 1
          - Industry match             -> weight 2
        Returns article dicts ordered by composite score desc, year desc.
        """
        if not topics and not industries:
            return []

        cql = """
        MATCH (a:Article)

        OPTIONAL MATCH (a)-[:COVERS_TOPIC]->(t:Topic)
        WHERE t.name IN $topics
        WITH a, count(DISTINCT t) AS direct_topic_hits

        OPTIONAL MATCH (a)-[:COVERS_TOPIC]->(t2:Topic)-[:RELATED_TO]->(tr:Topic)
        WHERE tr.name IN $topics
        WITH a, direct_topic_hits, count(DISTINCT tr) AS related_topic_hits

        OPTIONAL MATCH (a)-[:RELEVANT_TO]->(i:Industry)
        WHERE i.name IN $industries
        WITH a, direct_topic_hits, related_topic_hits, count(DISTINCT i) AS industry_hits

        WITH a,
             (direct_topic_hits * 3 + related_topic_hits + industry_hits * 2) AS score
        WHERE score > 0

        RETURN
          a.id            AS article_id,
          a.title         AS title,
          a.doi           AS doi,
          a.url           AS url,
          a.source        AS source,
          a.year          AS year,
          a.abstract      AS abstract,
          a.download_status AS download_status,
          a.has_fulltext  AS has_fulltext,
          a.has_pdf       AS has_pdf,
          a.local_path    AS local_path,
          score
        ORDER BY score DESC, a.year DESC
        LIMIT $limit
        """
        async with self._driver.session() as s:
            result = await s.run(
                cql,
                topics=topics or [],
                industries=industries or [],
                limit=limit,
            )
            return [dict(r) async for r in result]

    async def fulltext_search(self, query_text: str, limit: int = 20) -> list[dict]:
        """Full-text index fallback when topic/industry extraction yields nothing."""
        cql = """
        CALL db.index.fulltext.queryNodes("article_fulltext", $q)
        YIELD node AS a, score AS ft_score
        RETURN
          a.id            AS article_id,
          a.title         AS title,
          a.doi           AS doi,
          a.url           AS url,
          a.source        AS source,
          a.year          AS year,
          a.abstract      AS abstract,
          a.download_status AS download_status,
          a.has_fulltext  AS has_fulltext,
          a.has_pdf       AS has_pdf,
          a.local_path    AS local_path,
          ft_score        AS score
        ORDER BY score DESC
        LIMIT $limit
        """
        async with self._driver.session() as s:
            result = await s.run(cql, q=query_text, limit=limit)
            return [dict(r) async for r in result]

    async def get_chunk_ids_for_articles(self, article_ids: list[str]) -> list[str]:
        """Return all Chunk.id values belonging to the given Article ids."""
        cql = """
        MATCH (a:Article)-[:HAS_CHUNK]->(c:Chunk)
        WHERE a.id IN $ids
        RETURN c.id AS chunk_id
        """
        async with self._driver.session() as s:
            result = await s.run(cql, ids=article_ids)
            return [r["chunk_id"] async for r in result]

    # ── Status ────────────────────────────────────────────────────────────────

    async def get_status(self) -> dict:
        """Return counts of each node label."""
        cql = """
        MATCH (a:Article)
        WITH
          count(a) AS total_articles,
          count(CASE WHEN a.download_status = 'pdf'           THEN 1 END) AS pdf_count,
          count(CASE WHEN a.download_status = 'fulltext'      THEN 1 END) AS fulltext_count,
          count(CASE WHEN a.download_status = 'metadata_only' THEN 1 END) AS meta_count
        OPTIONAL MATCH (c:Chunk)
        WITH total_articles, pdf_count, fulltext_count, meta_count,
             count(c) AS total_chunks
        OPTIONAL MATCH (t:Topic)
        WITH total_articles, pdf_count, fulltext_count, meta_count, total_chunks,
             count(t) AS total_topics
        OPTIONAL MATCH (i:Industry)
        RETURN
          total_articles, pdf_count, fulltext_count, meta_count,
          total_chunks, total_topics, count(i) AS total_industries
        """
        async with self._driver.session() as s:
            result = await s.run(cql)
            record = await result.single()
            return dict(record) if record else {}
