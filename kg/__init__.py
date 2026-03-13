"""
kg/ – Neo4j + Qdrant knowledge graph subpackage for the manufacturing research agent.

Public API
----------
    from kg import KnowledgeAgent   # full pipeline: search + auto-download fallback
    from kg import GraphBuilder     # corpus -> Neo4j + Qdrant ingestion
    from kg import GraphSearcher    # query -> Neo4j graph -> Qdrant vector search
"""
from kg.knowledge_agent import KnowledgeAgent
from kg.graph_builder import GraphBuilder
from kg.graph_search import GraphSearcher

__all__ = ["KnowledgeAgent", "GraphBuilder", "GraphSearcher"]
