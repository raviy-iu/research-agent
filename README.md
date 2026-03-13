# Manufacturing Research Agent

A terminal-driven research agent that searches **IEEE, ScienceDirect, Taylor & Francis, MDPI, Springer, ACS, Wiley, SlideShare, and Medium** for academic papers and industry articles relevant to manufacturing industries.

Designed for: cement, steel, aluminum, tyre, oil & gas, specialty chemicals, paper & pulp, mining, automobile, and other heavy/process industries.

Topics covered: FMEA/PFMEA, digital twins, energy optimization, ESG goals, root-cause analysis, predictive maintenance, data-driven modeling, physics-based/hybrid modeling, anomaly detection, ODR generation, quality control, and more.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Installation](#installation)
3. [How to Run](#how-to-run)
4. [CLI Reference](#cli-reference)
5. [Prompt Templates](#prompt-templates)
6. [Knowledge-Base Corpus Builder](#knowledge-base-corpus-builder)
7. [Knowledge Graph (Neo4j + Qdrant)](#knowledge-graph-neo4j--qdrant)
8. [Architecture & Dataflow](#architecture--dataflow)
9. [File-to-File Integration Map](#file-to-file-integration-map)
10. [Output Format](#output-format)
11. [Sources & Coverage](#sources--coverage)
12. [Improving Search Quality Over Time](#improving-search-quality-over-time)
13. [Project Structure](#project-structure)
14. [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# 1. Clone / navigate to the project
cd C:\Users\ravi.yalamarthi\IU_Projects\research_agent

# 2. Create virtual environment and install dependencies
uv venv
uv sync --link-mode=copy        # --link-mode=copy required on cloud-synced drives

# 3. Run your first query
uv run main.py "FMEA cement kiln ring formation"

# 4. Use a pre-built template
uv run main.py --template fmea --set industry=cement --set equipment=kiln

# 5. See all templates
uv run main.py --list-templates
```

Results are saved to `outputs/YYYYMMDD_HHMMSS_<slug>.json`.

```bash
# Phase 2 — Download full text to local corpus
uv run main.py "FMEA cement kiln" --download      # search + download in one step
uv run download.py --all                           # download from all existing outputs

# Phase 3 — Knowledge Graph (requires Neo4j + Docker)
docker compose up -d qdrant                        # start Qdrant vector store
uv run kg_main.py build                            # ingest corpus into Neo4j + Qdrant
uv run kg_main.py search "FMEA cement kiln"        # two-stage graph + vector search
uv run kg_main.py status                           # show graph stats
```

---

## Installation

### Prerequisites
- Python 3.11 or higher
- [`uv`](https://docs.astral.sh/uv/) package manager
- **Neo4j** v5+ (for knowledge graph) — [Download Neo4j Desktop](https://neo4j.com/download/) or [Community Server](https://neo4j.com/download-center/#community)
- **Docker** (for Qdrant vector store) — [Get Docker](https://docs.docker.com/get-docker/)

### Setup

```bash
# Step 1 – Create virtual environment
uv venv

# Step 2 – Install all dependencies
#   IMPORTANT: On cloud-synced drives (OneDrive, SharePoint, etc.) always use --link-mode=copy
#   to avoid Windows error 396 (cloud hardlink restriction)
uv sync --link-mode=copy

# Step 3 – (Optional) Configure environment variables
copy .env.example .env
# Edit .env and set CROSSREF_EMAIL to your email for better CrossRef rate limits
```

### Environment Variables (`.env`)

**Research Agent variables:**

| Variable | Default | Description |
|---|---|---|
| `CROSSREF_EMAIL` | `research-agent@example.com` | Your email for CrossRef polite-pool (improves rate limits) |
| `RESULTS_PER_SOURCE` | `25` | Max results per source per query |
| `OUTPUT_DIR` | `outputs` | Directory for JSON result files |
| `SEMANTIC_SCHOLAR_API_KEY` | *(empty)* | Optional – raises S2 rate limit from 1 rps to 100 rps |
| `IEEE_API_KEY` | *(empty)* | Optional – reserved for future IEEE Xplore API integration |
| `ELSEVIER_API_KEY` | *(empty)* | Optional – reserved for future Elsevier Scopus integration |

**Knowledge Graph variables** (required for `kg_main.py`):

| Variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `password` | Neo4j password (set during installation) |
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant REST port |
| `QDRANT_COLLECTION` | `manufacturing_research` | Qdrant collection name |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model (384-dim, local, free) |
| `KG_CHUNK_WORDS` | `400` | Words per text chunk for embedding |
| `KG_CHUNK_OVERLAP` | `50` | Word overlap between consecutive chunks |
| `KB_DIR` | `knowledge_base` | Root directory of the local corpus |

All research-agent API keys are optional. The agent works fully without any keys using free public APIs.

---

## How to Run

### Mode 1 – Raw Query

Provide any natural-language query directly:

```bash
uv run main.py "FMEA cement kiln ring formation"
uv run main.py "digital twin steel blast furnace energy optimization"
uv run main.py "predictive maintenance aluminum smelter vibration"
uv run main.py "hybrid modeling rotary kiln shell temperature"
uv run main.py "root cause analysis tyre plant quality defect"
uv run main.py "ESG sustainability paper pulp mill carbon reduction"
```

### Mode 2 – Prompt Templates

Use a structured, reusable template with named placeholders:

```bash
# List all available templates (13 pre-built)
uv run main.py --list-templates

# FMEA analysis
uv run main.py --template fmea --set industry=cement --set equipment=kiln

# Digital twin
uv run main.py --template digital_twin --set industry=steel --set asset="blast furnace"

# Energy optimization
uv run main.py --template energy_opt --set industry=aluminum --set process=electrolysis

# Root cause analysis
uv run main.py --template root_cause --set industry=tyre --set failure_mode="belt delamination"

# Hybrid modeling with custom focus
uv run main.py --template hybrid_model \
    --set industry=cement \
    --set process="rotary kiln" \
    --set focus="PINN physics-informed shell temperature ring formation"

# ODR generation / operational insights
uv run main.py --template odr --set industry="oil and gas" --set kpi="specific energy consumption"
```

### Mode 3 – Filtered Sources

Restrict results to specific publishers:

```bash
# Academic publishers only (all routed through CrossRef)
uv run main.py "ring formation kiln" --sources springer,acs
uv run main.py "FMEA cement" --sources ieee,sciencedirect
uv run main.py "digital twin" --sources springer,wiley,mdpi

# Industry content only
uv run main.py "ring formation kiln" --sources slideshare,medium

# Mix academic + industry
uv run main.py "predictive maintenance" --sources ieee,springer,medium
```

### Additional Options

```bash
# Return more results (default: 25)
uv run main.py "digital twin cement" --max-results 50

# Save to a custom folder
uv run main.py "ESG steel plant" --output-dir results/esg_study

# Enable debug logging to see per-source HTTP details
uv run main.py "FMEA kiln" --verbose

# Combine all options
uv run main.py --template predictive_maint \
    --set industry=mining \
    --set equipment=conveyor \
    --max-results 40 \
    --sources ieee,springer,acs,medium \
    --output-dir results/mining_pm \
    --verbose
```

---

## CLI Reference

```
usage: research-agent [-h] [--template NAME] [--set KEY=VALUE]
                       [--list-templates] [--max-results N]
                       [--sources SOURCES] [--output-dir DIR] [-v]
                       [query]

positional arguments:
  query                 Raw research query (not needed when --template is used)

options:
  --template NAME       Pre-built template from prompts.json
  --set KEY=VALUE       Fill a template placeholder (repeatable)
  --list-templates      Print all templates with keys and exit
  --max-results N       Max articles to return (default: 25)
  --sources SOURCES     Comma-separated source filter (default: all)
                          Academic via CrossRef: ieee, sciencedirect,
                            taylorfrancis, mdpi, springer, acs, wiley
                          Other: medium, slideshare, all
  --output-dir DIR      Output directory (default: outputs/)
  -v, --verbose         Enable debug logging
```

---

## Prompt Templates

Templates live in `prompts.json` and are designed to be refined over time.

### Pre-built Templates

| Template | Required Keys | Optional Key (default focus) |
|---|---|---|
| `fmea` | industry, equipment | root cause corrective action severity |
| `digital_twin` | industry, asset | predictive maintenance process optimization |
| `energy_opt` | industry, process | machine learning data-driven ESG |
| `production_opt` | industry | reinforcement learning simulation bottleneck |
| `esg` | industry | energy efficiency renewable waste reduction |
| `root_cause` | industry, failure_mode | ML sensor data FMEA fishbone Ishikawa |
| `predictive_maint` | industry, equipment | vibration acoustic thermal remaining useful life |
| `data_driven` | industry, model_type | neural network regression time series |
| `hybrid_model` | industry, process | PINN grey-box semi-mechanistic transfer learning |
| `odr` | industry, kpi | dashboard anomaly alert prescriptive analytics |
| `anomaly_detect` | industry | autoencoder isolation forest SPC unsupervised |
| `quality_control` | industry, product | Six Sigma SPC machine vision deep learning |
| `efficiency` | industry | lean manufacturing TPM waste reduction |

### How to Improve a Template

1. Open `prompts.json`
2. Locate the template (e.g., `"fmea"`)
3. Edit the `template` string — add or reorder academic keywords
4. Increment `version` by 1 (so output JSON records which version produced which results)
5. Re-run the query and compare with the previous output

```json
"fmea": {
    "description": "FMEA / PFMEA failure mode analysis",
    "template": "FMEA PFMEA failure mode effects analysis {industry} {equipment} reliability risk {focus}",
    "required_keys": ["industry", "equipment"],
    "optional_keys": {
        "focus": "root cause corrective action severity occurrence detection"
    },
    "version": 2,
    "notes": "Added 'risk priority number RPN' for v2 – gave better IEEE results"
}
```

The saved JSON always records `"template": { "name", "version", "keys", "template_string" }` so you can trace which template version produced each result set.

---

## Knowledge-Base Corpus Builder

After the agent finds articles, you can download their full content to a local corpus with two tools:

| Tool | Purpose |
|---|---|
| `downloader.py` | Core engine (async, importable) |
| `download.py` | Standalone CLI |
| `--download` flag on `main.py` | Search + download in one step |

### What gets downloaded

| Source | What happens |
|---|---|
| **Medium** | Full article text scraped and saved as `fulltext.txt` |
| **SlideShare** | Slide text scraped and saved as `fulltext.txt` |
| **MDPI** (10.3390 DOI) | Open-access PDF fetched via [Unpaywall](https://unpaywall.org/) and saved as `paper.pdf` |
| **IEEE / Springer / ACS / Wiley / ScienceDirect / TaylorFrancis** | Unpaywall queried for any legal open-access copy; PDF saved if found; metadata+abstract only if paywalled |
| **Academic** (Semantic Scholar) | Unpaywall on DOI, then direct URL scrape as fallback |

> **Paywall policy:** Only legally accessible copies are downloaded. Paywall content is never bypassed. Many MDPI papers and ~30–40% of recent academic papers have open-access versions discoverable via Unpaywall.

### Corpus layout

```
knowledge_base/
  index.json                    # master index (keyed by DOI or URL)
  papers/
    IEEE/
      10.1109_rams48127_2025_a1b2c3d4/
        metadata.json           # title, source, doi, authors, year, download_status
        paper.pdf               # PDF (if open-access copy found)
    MDPI/
      10.3390_en16010123_a1b2c3d4/
        metadata.json
        paper.pdf
    Medium/
      https___medium.com_..._a1b2c3d4/
        metadata.json
        fulltext.txt            # scraped article text
    SlideShare/
      ...
```

### Mode 1 — Search + download in one step

```bash
# Search and immediately download to knowledge_base/
uv run main.py "FMEA cement kiln" --download

# Custom kb directory
uv run main.py --template fmea --set industry=cement --set equipment=kiln \
    --download --kb-dir corpus/cement_fmea
```

### Mode 2 — Download from existing output JSON(s)

```bash
# Single file
uv run download.py outputs/20260310_170704_fmea_cement_kiln.json

# Multiple files merged (deduplication applied across all files)
uv run download.py outputs/file1.json outputs/file2.json outputs/file3.json

# ALL JSON files in outputs/ at once
uv run download.py --all

# Custom directory + email for Unpaywall (any email works)
uv run download.py --all --kb-dir my_corpus --email you@company.com

# Limit concurrency (default 4) — be polite to servers
uv run download.py --all --max-concurrent 2

# Skip sources you don't need
uv run download.py --all --skip-sources SlideShare,Medium

# Verbose: see per-article decisions
uv run download.py --all -v
```

### `download.py` CLI reference

| Flag | Default | Description |
|---|---|---|
| `json_files` (positional) | — | One or more output JSON files |
| `--all` | false | Process all `*.json` in `--output-dir` |
| `--output-dir DIR` | `outputs/` | Directory scanned by `--all` |
| `--kb-dir DIR` | `knowledge_base/` | Root directory for the corpus |
| `--email EMAIL` | value from `.env` | Unpaywall API email (any email works) |
| `--max-concurrent N` | 4 | Simultaneous HTTP connections |
| `--skip-sources` | — | Comma-separated sources to skip |
| `-v, --verbose` | false | Show per-article debug log |

### Incremental runs

The downloader is **incremental**: articles already present in the corpus with status `pdf` or `fulltext` are skipped automatically. You can safely re-run after adding new search results — only new articles will be processed.

### Using the corpus (RAG / LLM)

```
knowledge_base/
  index.json            <- load this to find all articles and their local paths
  papers/
    MDPI/.../paper.pdf  <- feed to any PDF-capable LLM / RAG pipeline
    Medium/.../fulltext.txt  <- plain text, ready for chunking / embedding
```

The `index.json` master index has one entry per article:

```json
{
  "doi:10.3390/en16010123": {
    "title": "Energy Efficiency in Cement Manufacturing",
    "source": "MDPI",
    "doi": "10.3390/en16010123",
    "url": "https://doi.org/10.3390/en16010123",
    "year": 2023,
    "authors": ["Smith J.", "Patel R."],
    "abstract": "...",
    "download_status": "pdf",
    "downloaded_at": "2026-03-10T19:30:00",
    "local_path": "papers/MDPI/10.3390_en16010123_a1b2c3d4",
    "oa_url": "https://www.mdpi.com/1996-1073/16/1/123/pdf"
  }
}
```

---

## Knowledge Graph (Neo4j + Qdrant)

The knowledge graph layer sits on top of the local corpus and enables **structured, efficient retrieval** instead of brute-force similarity search across thousands of documents.

### Overview

Two-stage search pipeline:

1. **Neo4j graph traversal** — extracts topics and industries from the query using rule-based regex (matched against `TOPIC_TERMS` and `INDUSTRY_TERMS` in `config.py`), then traverses the graph to find relevant `Article` nodes. Scores them by: direct topic match (×3) + 1-hop `RELATED_TO` topic (×1) + industry match (×2). Returns top 20 candidates.
2. **Qdrant vector search** — embeds the query with `all-MiniLM-L6-v2` and runs cosine similarity **restricted to chunk IDs belonging to the 20 Neo4j candidates** — not the entire corpus. Returns top-k ranked text excerpts.

If Neo4j has no matching articles, the agent **automatically** runs the research agent + downloader to find and ingest new papers, then retries.

### Data Flow

```
User Query
    |
    v
[kg_main.py search]
    |
    v   regex vs TOPIC_TERMS + INDUSTRY_TERMS (config.py)
Extract topics & industries from query
    |
    v
Neo4j Cypher graph search
  MATCH (a:Article)-[:COVERS_TOPIC]->(t:Topic)
  WHERE t.name IN [matched_topics]
  Score = direct_topic_hits*3 + related_topic_hits + industry_hits*2
  LIMIT 20
    |
    +-- Results found? --------> collect article_ids (up to 20)
    |                            Qdrant cosine search (filtered to those IDs only)
    |                            Return top-k ranked chunks + article metadata
    |
    +-- No results? -----------> [Auto-expand]
                                   agent.run(query)          -- search databases
                                   download_corpus()         -- download open-access
                                   graph_builder.ingest()    -- load into Neo4j+Qdrant
                                   Retry search once
```

### Neo4j Graph Schema

**Node types:**

| Node | Key Properties |
|---|---|
| `Article` | `id` (doi/url), `title`, `doi`, `url`, `source`, `year`, `abstract`, `download_status`, `has_pdf`, `has_fulltext`, `local_path` |
| `Author` | `name` |
| `Publisher` | `name` (IEEE, MDPI, Medium, etc.) |
| `Topic` | `name` (seeded from `TOPIC_TERMS` — 45 entries) |
| `Industry` | `name` (seeded from `INDUSTRY_TERMS` — 28 entries) |
| `Chunk` | `id`, `text` (preview), `chunk_index`, `article_id` |

**Relationships:**

| Relationship | Description |
|---|---|
| `(Article)-[:AUTHORED_BY]->(Author)` | Paper authorship |
| `(Article)-[:PUBLISHED_BY]->(Publisher)` | Publisher (IEEE, MDPI, etc.) |
| `(Article)-[:COVERS_TOPIC]->(Topic)` | Topics matched from title + abstract |
| `(Article)-[:RELEVANT_TO]->(Industry)` | Industries matched from title + abstract |
| `(Article)-[:HAS_CHUNK]->(Chunk)` | Text chunks (vectors stored in Qdrant) |
| `(Topic)-[:RELATED_TO]->(Topic)` | Pre-seeded topic synonyms and logical groups |
| `(Industry)-[:RELATED_TO]->(Industry)` | Industry synonyms (aluminium/aluminum, tyre/tire, etc.) |

**Pre-seeded topic relationships** (examples):
- `FMEA` ↔ `PFMEA` ↔ `failure mode effects analysis`
- `predictive maintenance` -> `condition monitoring` -> `fault detection` -> `remaining useful life`
- `digital twin` -> `hybrid modeling` -> `physics-informed` -> `data-driven modeling`
- `rotary kiln` -> `ring formation` -> `shell temperature` -> `clinker`
- `energy optimization` -> `process optimization` -> `energy efficiency` -> `ESG`

### Prerequisites

```bash
# 1. Install Neo4j (Desktop or Community Server v5+)
#    https://neo4j.com/download/
#    After install: start the database, note the password you set

# 2. Install Docker (for Qdrant)
#    https://docs.docker.com/get-docker/

# 3. Configure .env
copy .env.example .env
# Set NEO4J_PASSWORD to whatever you set during Neo4j installation
```

### Setup

```bash
# Step 1 — Configure credentials in .env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here

# Step 2 — Start Qdrant via Docker
docker compose up -d qdrant
# Verify: http://localhost:6333/dashboard

# Step 3 — Dependencies (already installed if you ran uv sync)
uv sync --link-mode=copy
```

### Build the Graph

Ingest the local corpus (`knowledge_base/`) into Neo4j + Qdrant:

```bash
# First: seed the corpus (if knowledge_base/ is empty)
uv run main.py "FMEA cement kiln" --download --max-results 40
uv run main.py "predictive maintenance steel blast furnace" --download --max-results 40

# Then: ingest everything into the graph
uv run kg_main.py build

# Force re-ingest (clears Qdrant collection first, re-embeds everything)
uv run kg_main.py build --force

# Custom knowledge_base location
uv run kg_main.py build --kb-dir my_corpus
```

The build step:
1. Reads `knowledge_base/index.json`
2. Skips articles already in Neo4j (incremental by default)
3. Extracts Topics + Industries via regex from title + abstract
4. Creates Article, Author, Publisher, Topic, Industry nodes and relationships
5. Extracts text from PDF/fulltext.txt/abstract
6. Chunks text (400 words, 50-word overlap) and embeds with `all-MiniLM-L6-v2`
7. Upserts chunk embeddings to Qdrant with `article_id` in payload

### Search the Graph

```bash
# Basic search
uv run kg_main.py search "FMEA cement kiln ring formation"
uv run kg_main.py search "predictive maintenance steel blast furnace"
uv run kg_main.py search "digital twin energy optimization aluminum smelter"

# Limit results
uv run kg_main.py search "root cause analysis tyre defect" --top 5

# Show extracted topics/industries (for debugging)
uv run kg_main.py search "ring formation rotary kiln" --show-terms
# Output:
#   Topics:     ['ring formation', 'rotary kiln', 'shell temperature', 'clinker']
#   Industries: ['cement', 'kiln']

# Disable auto-download fallback (return empty if not in graph)
uv run kg_main.py search "very niche query" --no-auto-download

# Debug logging
uv run kg_main.py search "FMEA cement" -v
```

**Example output:**
```
3 result(s) for: FMEA cement kiln ring formation

1. Failure Mode Analysis of Cement Kiln Thermal Processes  (IEEE, 2024)  score=0.847
   https://ieeexplore.ieee.org/document/10935068
   This paper presents a comprehensive FMEA study of rotary kiln operations,
   focusing on ring formation, thermal profile anomalies...

2. Physics-Informed Digital Twin for Rotary Kiln Shell Temperature  (MDPI, 2023)  score=0.791
   https://doi.org/10.3390/en16010123
   A hybrid modeling approach combining PFMEA risk assessment with real-time...
```

### Status

```bash
uv run kg_main.py status
```

```
Neo4j Graph
  Total Articles     142
    PDF downloaded    38
    Full text scraped 61
    Metadata only     43
  Chunks            1284
  Topic nodes         45
  Industry nodes      28

Qdrant Vector Store
  collection   manufacturing_research
  total_chunks 1284
  vector_size  384
  distance     Cosine
  status       green
```

### Ingest from JSON

Ingest articles from a specific search-output JSON without re-searching:

```bash
# Ingest from one file
uv run kg_main.py ingest outputs/20260310_170704_fmea_cement_kiln.json

# Ingest from multiple files (deduplicated across files)
uv run kg_main.py ingest outputs/file1.json outputs/file2.json

# Custom kb-dir
uv run kg_main.py ingest outputs/file.json --kb-dir my_corpus
```

### `kg_main.py` CLI Reference

```
uv run kg_main.py <subcommand> [options]
```

| Subcommand | Options | Description |
|---|---|---|
| `build` | `--kb-dir DIR` | Ingest `knowledge_base/` into Neo4j + Qdrant |
| `build` | `--force` | Re-ingest all (clears Qdrant first) |
| `search "query"` | `--top N` (default 10) | Two-stage graph + vector search |
| `search "query"` | `--no-auto-download` | Disable auto-expand on cache miss |
| `search "query"` | `--show-terms` | Print extracted topics/industries |
| `status` | — | Show Neo4j + Qdrant statistics |
| `ingest FILE` | `--kb-dir DIR` | Ingest from search-output JSON file(s) |
| *(any)* | `-v, --verbose` | Enable debug logging |

### Auto-Download Fallback

When `search` finds nothing in Neo4j, it automatically:

1. Runs `agent.run(query, max_results=30)` — searches IEEE, ScienceDirect, Springer, etc.
2. Runs `download_corpus()` — downloads open-access PDFs and web articles
3. Runs `graph_builder.ingest_articles()` — loads new articles into Neo4j + Qdrant
4. Retries the search once

```bash
$ uv run kg_main.py search "aluminum smelter energy optimization carbon footprint"
# -> No results found in the knowledge graph. Searching and downloading new papers...
# -> Found 28 new articles
# -> Download complete: PDF=5 | Fulltext=8 | Metadata-only=15
# -> Ingesting into knowledge graph...
# -> Ingestion complete: ingested=28  skipped=0  failed=0
# -> Retrying search after ingestion...
# -> 10 result(s) for: aluminum smelter energy optimization carbon footprint
```

### Chunking and Embedding

| Setting | Default | Description |
|---|---|---|
| Model | `all-MiniLM-L6-v2` | Local, free, 384-dim, ~90 MB download on first use |
| Chunk size | 400 words | Sliding window over word tokens |
| Overlap | 50 words | Words shared between consecutive chunks |
| Text priority | PDF > fulltext.txt > title+abstract | Best available text per article |

The model is downloaded automatically on first use (from HuggingFace Hub) and cached locally. No API key needed.

---

## Architecture & Dataflow

```
User Terminal
     |
     | uv run main.py "<query>" [--template X --set K=V] [--sources S] [--max-results N]
     v
+--------------------+
|      main.py       |   Entry point
|  - parse_args()    |   Parses CLI arguments
|  - _resolve_query()|   Raw query OR renders template → query string
+--------------------+
          |
          | query_text (str)
          v
+--------------------+
|  query_builder.py  |   Expands query
|  - build_query()   |   Detects industry/topic terms
|                    |   Appends "manufacturing industrial process" if no industry term found
+--------------------+
          |
          | QueryBundle(raw, expanded, keywords[], has_industry_term, has_topic_term)
          v
+--------------------+
|     agent.py       |   Orchestrates parallel fetching
|  - run()           |
|  - _build_sources()|   Selects active sources based on --sources filter
+--------------------+
          |
          | asyncio.gather() -- all sources fire concurrently
          |
    +-----+-----+----------+----------+
    |     |     |          |          |
    v     v     v          v          v
+-------+ +---+ +--------+ +--------+ +----------+
|Cross  | |S2 | |Slide   | |Medium  | (optional) |
|Ref    | |API| |Share   | |RSS     |            |
|crossref| |se | |slide   | |medium  |            |
|.py    | |ma | |share   | |.py     |            |
+-------+ +---+ +--------+ +--------+            |
    |       |        |          |                 |
    | 7 parallel     |          |                 |
    | sub-requests   |          |                 |
    | (one per DOI   |          |                 |
    |  prefix)       |          |                 |
    v       v        v          v
+-------+ +---+ +--------+ +--------+
|IEEE   | |Ac | |Slide   | |Medium  |
|SD     | |ad | |Share   | |articles|
|T&F    | |em | |present | +--------+
|MDPI   | |ic | |ations  |
|Spring | +---+ +--------+
|ACS    |
|Wiley  |
+-------+
          |
          | All results merged → list[Article]
          v
+--------------------+
|     agent.py       |   Post-processing
|  _deduplicate()    |   DOI (primary) or URL (fallback) deduplication
|                    |   Priority: IEEE > SD > T&F > MDPI > Springer > ACS > Wiley
|                    |             > Academic > SlideShare > Medium
|  _interleave_      |   Round-robin across sources (5 IEEE, 5 SD, 5 T&F, ...)
|  by_source()       |   for diversity in the final result set
|  [:max_results]    |   Truncate to --max-results (default 25)
+--------------------+
          |
          | list[Article] (title, source, url, doi, abstract, year, authors)
          v
+--------------------+
|     agent.py       |   Serialisation
|  save_results()    |   Writes timestamped JSON to outputs/
+--------------------+
          |
          v
   outputs/YYYYMMDD_HHMMSS_<slug>.json
```

### Query Expansion Logic

```
User input: "energy consumption reduction"
    |
    | No INDUSTRY_TERM detected (cement/steel/tyre/...)
    v
Expanded: "energy consumption reduction manufacturing industrial process"
    |
    | Has INDUSTRY_TERM:
User input: "FMEA cement kiln"
    v
Expanded: "FMEA cement kiln"  (unchanged – already has industry context)
```

---

## File-to-File Integration Map

```
prompts.json
    └── read by ──────────────────► prompt_template.py
                                        ├── PromptTemplate.render()
                                        ├── list_templates()
                                        └── called by ───────────► main.py
                                                                        └── _resolve_query()
                                                                                │
config.py                                                                       │
    ├── DOI_PREFIXES  ─────────────► sources/crossref.py                        │
    ├── PREFIX_TO_SOURCE ──────────► sources/semantic_scholar.py                 │
    ├── TOPIC_TERMS   ─────────────► query_builder.py                            │
    ├── INDUSTRY_TERMS ───────────► query_builder.py                             │
    ├── MEDIUM_TAGS   ─────────────► sources/medium.py                           │
    ├── CONCURRENCY   ─────────────► sources/*.py (Semaphore values)             │
    ├── TIMEOUT_SECONDS ──────────► sources/*.py (httpx timeout)                 │
    └── settings (Settings) ──────► all files via `from config import settings`  │
                                                                                  │
query_builder.py ◄──────────────────────────────────────────────────────────────┘
    └── build_query(user_input)
            └── returns QueryBundle ──────────────────────────────► agent.py
                                                                        │
                                                                        │ fan-out
                                                              ┌─────────┴──────────┐
                                                              │                    │
sources/base.py ◄─── inherited by all source modules         │                    │
    ├── Article (dataclass)         sources/crossref.py       sources/medium.py    │
    └── BaseSource (ABC)            sources/semantic_scholar.py                    │
                                    sources/slideshare.py      sources/medium.py   │
                                              │                                    │
                                              └─────── list[Article] ─────────────►
                                                                        │
                                                                    agent.py
                                                                        ├── _deduplicate()
                                                                        ├── _interleave_by_source()
                                                                        └── save_results()
                                                                                │
                                                                                ▼
                                                                     outputs/*.json
```

### Data Object Flow

```
str (user CLI input)
    │
    ▼ query_builder.build_query()
QueryBundle
    ├── .raw          "FMEA cement kiln"
    ├── .expanded     "FMEA cement kiln" (or + "manufacturing industrial process")
    ├── .keywords     ["fmea", "cement", "kiln"]
    ├── .has_industry_term  True
    └── .has_topic_term     True
    │
    ▼ Source.fetch(bundle)          (parallel across all sources)
list[Article]
    ├── .title        "Failure Mode Analysis of Cement Kiln..."
    ├── .source       "IEEE"
    ├── .url          "https://ieeexplore.ieee.org/document/12345"
    ├── .doi          "10.1109/access.2024.12345"
    ├── .abstract     "This paper presents..."
    ├── .year         2024
    └── .authors      ["Smith J.", "Patel R."]
    │
    ▼ agent._deduplicate() + _interleave_by_source()
list[Article]   (deduplicated, interleaved, truncated)
    │
    ▼ agent.save_results()
outputs/20260310_183000_fmea_cement_kiln.json
```

---

## Output Format

Each run produces one JSON file in the `outputs/` directory:

**Filename**: `YYYYMMDD_HHMMSS_<query-slug>.json`

```json
{
  "query": "FMEA cement kiln ring formation",
  "expanded_query": "FMEA cement kiln ring formation",
  "template": {
    "name": "fmea",
    "version": 1,
    "keys": {
      "industry": "cement",
      "equipment": "kiln"
    },
    "template_string": "FMEA PFMEA failure mode effects analysis {industry} {equipment} reliability risk {focus}"
  },
  "timestamp": "2026-03-10T18:30:00.123456",
  "total_results": 30,
  "results": [
    {
      "title": "Failure Mode and Effect Analysis for Cement Kiln Process",
      "source": "IEEE",
      "url": "https://ieeexplore.ieee.org/document/1234567",
      "doi": "10.1109/access.2024.1234567",
      "abstract": "This paper presents a systematic FMEA approach...",
      "year": 2024,
      "authors": ["Smith, J.", "Patel, R."]
    },
    {
      "title": "Digital Twin for Rotary Kiln Ring Detection",
      "source": "ScienceDirect",
      "url": "https://doi.org/10.1016/j.ces.2024.120123",
      "doi": "10.1016/j.ces.2024.120123",
      "abstract": "Ring formation in rotary kilns...",
      "year": 2024,
      "authors": ["Chen, L.", "Wang, H."]
    }
  ]
}
```

**Note**: `"template"` is `null` when a raw query is used (no `--template` flag).

### Result Fields

| Field | Type | Description |
|---|---|---|
| `title` | string | Full article title |
| `source` | string | Publisher: `IEEE`, `ScienceDirect`, `TaylorFrancis`, `MDPI`, `Springer`, `ACS`, `Wiley`, `Academic`, `SlideShare`, `Medium` |
| `url` | string | Direct link to view or download the article |
| `doi` | string | DOI (empty for Medium/SlideShare articles) |
| `abstract` | string | Abstract or summary (may be empty) |
| `year` | int or null | Publication year |
| `authors` | list[str] | Author names |

---

## Sources & Coverage

| Source | Access Method | URL Pattern | Notes |
|---|---|---|---|
| **IEEE** | CrossRef API (DOI prefix `10.1109`) | `https://ieeexplore.ieee.org/document/<N>` | Clean document URL extracted from arnumber |
| **ScienceDirect** | CrossRef API (DOI prefix `10.1016`) | `https://doi.org/10.1016/...` | Redirects to sciencedirect.com |
| **Taylor & Francis** | CrossRef API (DOI prefix `10.1080`) | `https://doi.org/10.1080/...` | Redirects to tandfonline.com |
| **MDPI** | CrossRef API (DOI prefix `10.3390`) | `https://doi.org/10.3390/...` | Open access; redirects to mdpi.com |
| **Springer** | CrossRef API (DOI prefix `10.1007`) | `https://doi.org/10.1007/...` | Redirects to link.springer.com |
| **ACS** | CrossRef API (DOI prefix `10.1021`) | `https://doi.org/10.1021/...` | Redirects to pubs.acs.org |
| **Wiley** | CrossRef API (DOI prefix `10.1002`) | `https://doi.org/10.1002/...` | Redirects to onlinelibrary.wiley.com |
| **Semantic Scholar** | S2 Graph API (free, 1 rps) | `https://doi.org/<doi>` | Broad academic coverage; 429s are auto-retried |
| **SlideShare** | HTML scraper (httpx + BeautifulSoup) | `https://www.slideshare.net/...` | Industry presentations; graceful 403 fallback |
| **Medium** | RSS tag feeds (feedparser) | `https://medium.com/...` | Industry blogs; relevance-filtered |

### Adding a New Publisher

1. Find the publisher's CrossRef DOI prefix (search at [crossref.org](https://www.crossref.org/))
2. Add one line to `config.py`:
   ```python
   DOI_PREFIXES["NewPublisher"] = "10.XXXX"
   ```
3. Add the publisher to `_SOURCE_PRIORITY` in `agent.py`
4. That's it — CrossRef source picks it up automatically

---

## Improving Search Quality Over Time

The `prompts.json` file is designed as a living document. The workflow:

```
Run query                →  Review results in outputs/*.json
    │                              │
    │                    Find gaps or irrelevant results
    │                              │
    └──────────────────► Edit prompts.json
                              ├── Refine template string (add/remove keywords)
                              ├── Adjust optional key defaults
                              └── Increment "version" field
                                         │
                                    Re-run query
                                         │
                                  Compare result JSON files
                                  (template.version tracks which version produced what)
```

### Tips for Better Templates

- **Be specific with technical terms**: `"PFMEA severity occurrence detection RPN"` outperforms `"failure analysis"`
- **Add standard abbreviations**: `"RCA FTA 8D Ishikawa"` alongside spelled-out terms
- **Combine methodology + application**: `"physics-informed neural network rotary kiln temperature"` is more targeted than either alone
- **Use field-standard keywords**: Check the terminology used in abstracts of papers you already know are relevant
- **For SlideShare/Medium**, add operational terms: `"CO monitoring back pressure kiln operator"` surfaces practical plant presentations

---

## Project Structure

```
research_agent/
│
├── main.py                 # CLI entry point — parse args, resolve query, call agent
│                           #   Flags: --download, --kb-dir
├── agent.py                # Orchestrate sources, deduplicate, interleave, save JSON
├── config.py               # Settings (pydantic), DOI prefixes, topic/industry keywords
│                           #   Includes Neo4j + Qdrant + embedding settings
├── query_builder.py        # Query expansion: detects missing industry terms
├── prompt_template.py      # Template engine: load/render/validate prompts.json templates
│
├── downloader.py           # Async download engine (Unpaywall + web scraper)
│                           #   Builds local knowledge-base corpus
├── download.py             # Standalone CLI for downloader.py
│
├── kg_main.py              # Knowledge graph CLI (build / search / status / ingest)
├── docker-compose.yml      # Qdrant vector DB via Docker (port 6333)
│
├── prompts.json            # 13 pre-built templates (edit to improve search quality)
├── pyproject.toml          # Project metadata and pip dependencies (managed by uv)
├── .env.example            # Environment variable template — copy to .env and edit
├── .env                    # Your local secrets (not committed to git)
│
├── sources/                # One module per search data source
│   ├── base.py             # Article dataclass + BaseSource abstract class
│   ├── crossref.py         # CrossRef API — IEEE, ScienceDirect, T&F, MDPI, Springer, ACS, Wiley
│   ├── semantic_scholar.py # Semantic Scholar Graph API (free, 1 rps)
│   ├── medium.py           # Medium RSS feeds (12 manufacturing tags)
│   └── slideshare.py       # SlideShare HTML scraper (industry presentations)
│
├── kg/                     # Neo4j + Qdrant knowledge-graph subpackage
│   ├── __init__.py         # Exports KnowledgeAgent, GraphBuilder, GraphSearcher
│   ├── neo4j_manager.py    # Async Neo4j driver: schema setup, all Cypher CRUD
│   ├── embedder.py         # all-MiniLM-L6-v2 embeddings + word-based text chunker
│   ├── qdrant_manager.py   # Qdrant collection management, chunk upsert, filtered search
│   ├── text_extractor.py   # Text from PDF (pdfplumber) / fulltext.txt / abstract
│   ├── graph_builder.py    # Corpus -> Neo4j + Qdrant ingestion pipeline
│   ├── graph_search.py     # Two-stage: Neo4j graph filter -> Qdrant vector search
│   └── knowledge_agent.py  # Full orchestration with auto-download fallback
│
├── outputs/                # Auto-created; stores all JSON result files
│   └── YYYYMMDD_HHMMSS_<slug>.json
│
├── knowledge_base/         # Auto-created by downloader.py
│   ├── index.json          # Master index: all downloaded articles + status
│   └── papers/
│       ├── IEEE/           # One folder per source
│       ├── MDPI/
│       ├── Medium/
│       └── .../
│           └── <safe_id>/
│               ├── metadata.json
│               ├── paper.pdf    (if open-access PDF found via Unpaywall)
│               └── fulltext.txt (if web article scraped — Medium/SlideShare)
│
└── qdrant_data/            # Auto-created by Docker volume; persists Qdrant vectors
```

### Dependency Graph

```
main.py
  ├── imports agent.py
  ├── imports config.py          (Settings, settings singleton)
  ├── imports query_builder.py   (build_query)
  └── imports prompt_template.py (list_templates, parse_set_args, render, get_template, show_template_preview)

agent.py
  ├── imports config.py          (settings)
  ├── imports query_builder.py   (QueryBundle, build_query)
  ├── imports sources/base.py    (Article)
  ├── imports sources/crossref.py
  ├── imports sources/semantic_scholar.py
  ├── imports sources/slideshare.py
  └── imports sources/medium.py

sources/crossref.py
  ├── imports config.py          (DOI_PREFIXES, PREFIX_TO_SOURCE, TIMEOUT_SECONDS, settings)
  └── imports sources/base.py    (Article, BaseSource)

sources/semantic_scholar.py
  ├── imports config.py          (PREFIX_TO_SOURCE, TIMEOUT_SECONDS, settings)
  └── imports sources/base.py    (Article, BaseSource)

sources/medium.py
  ├── imports config.py          (MEDIUM_TAGS, TIMEOUT_SECONDS, settings)
  └── imports sources/base.py    (Article, BaseSource)

sources/slideshare.py
  ├── imports config.py          (TIMEOUT_SECONDS, settings)
  └── imports sources/base.py    (Article, BaseSource)

prompt_template.py
  └── reads prompts.json         (at runtime via json.loads)

query_builder.py
  └── imports config.py          (INDUSTRY_TERMS, TOPIC_TERMS)

downloader.py
  └── (standalone — no internal imports from this project)

download.py
  ├── imports config.py          (settings)
  └── imports downloader.py      (download_corpus)

kg_main.py
  ├── imports config.py          (settings)
  ├── imports kg/__init__.py     (KnowledgeAgent, GraphBuilder, GraphSearcher)
  ├── imports kg/neo4j_manager.py
  └── imports kg/qdrant_manager.py

kg/knowledge_agent.py
  ├── imports agent.py           (run)
  ├── imports downloader.py      (download_corpus)
  ├── imports config.py          (settings)
  ├── imports kg/graph_builder.py
  └── imports kg/graph_search.py

kg/graph_builder.py
  ├── imports config.py          (TOPIC_TERMS, INDUSTRY_TERMS, settings)
  ├── imports kg/neo4j_manager.py
  ├── imports kg/qdrant_manager.py
  ├── imports kg/embedder.py
  └── imports kg/text_extractor.py

kg/graph_search.py
  ├── imports config.py          (TOPIC_TERMS, INDUSTRY_TERMS)
  ├── imports kg/neo4j_manager.py
  ├── imports kg/qdrant_manager.py
  └── imports kg/embedder.py

kg/neo4j_manager.py
  └── imports config.py          (settings, TOPIC_TERMS, INDUSTRY_TERMS)

kg/qdrant_manager.py
  ├── imports config.py          (settings)
  └── imports kg/embedder.py     (embedding_dim)

kg/embedder.py
  └── imports config.py          (settings)

kg/text_extractor.py
  └── imports config.py          (settings)
```

---

## Troubleshooting

**Research agent:**

| Problem | Cause | Fix |
|---|---|---|
| `error 396` on `uv sync` | Cloud-synced drive (OneDrive) blocks hardlinks | Use `uv sync --link-mode=copy` |
| `UnicodeEncodeError` in terminal | Windows cp1252 console encoding | Avoid `→` `·` `–` in Rich output; use `->`, `\|`, `-` |
| Semantic Scholar rate limit warnings | Free tier is 1 rps shared | Normal — 429s are auto-retried. Set `SEMANTIC_SCHOLAR_API_KEY` in `.env` for 100 rps |
| SlideShare returns 0 results | Bot detection (HTTP 403) | Expected — SlideShare blocks scrapers intermittently. Use `--sources slideshare` and retry later |
| No Springer/ACS results for a query | Query terms too specific / not in CrossRef index | Broaden query or use `--verbose` to see per-prefix counts |
| Template key error | Missing required `--set` value | Run `--list-templates` to see required keys for the template |

**Knowledge graph (kg_main.py):**

| Problem | Cause | Fix |
|---|---|---|
| `ServiceUnavailable` connecting to Neo4j | Neo4j not running or wrong URI | Start Neo4j Desktop/Server; check `NEO4J_URI` in `.env` |
| `AuthError` connecting to Neo4j | Wrong password | Set `NEO4J_PASSWORD` in `.env` to match your Neo4j installation |
| `Connection refused` for Qdrant | Qdrant Docker container not running | Run `docker compose up -d qdrant`; check `docker ps` |
| `knowledge_base/index.json not found` | Corpus not yet downloaded | Run `uv run main.py "your query" --download` first |
| `build` ingests 0 articles | All already in graph (incremental) | Use `uv run kg_main.py build --force` to re-ingest everything |
| `search` returns no results | Query topics not in graph / no corpus | Run `build` first; or let auto-download add papers (remove `--no-auto-download`) |
| Embedding model download hangs | First-time HuggingFace download (~90 MB) | Wait — `all-MiniLM-L6-v2` downloads once and caches; needs internet on first run |
| Qdrant `points_count` is 0 after build | Build ran but Qdrant was not running | Start Qdrant and run `uv run kg_main.py build --force` |

---

*No API keys required. All sources use free public APIs or RSS feeds.*
