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
7. [Architecture & Dataflow](#architecture--dataflow)
8. [File-to-File Integration Map](#file-to-file-integration-map)
9. [Output Format](#output-format)
10. [Sources & Coverage](#sources--coverage)
11. [Improving Search Quality Over Time](#improving-search-quality-over-time)
12. [Project Structure](#project-structure)

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

---

## Installation

### Prerequisites
- Python 3.11 or higher
- [`uv`](https://docs.astral.sh/uv/) package manager

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

| Variable | Default | Description |
|---|---|---|
| `CROSSREF_EMAIL` | `research-agent@example.com` | Your email for CrossRef polite-pool (improves rate limits) |
| `RESULTS_PER_SOURCE` | `25` | Max results per source per query |
| `OUTPUT_DIR` | `outputs` | Directory for JSON result files |
| `SEMANTIC_SCHOLAR_API_KEY` | *(empty)* | Optional – raises S2 rate limit from 1 rps to 100 rps |
| `IEEE_API_KEY` | *(empty)* | Optional – reserved for future IEEE Xplore API integration |
| `ELSEVIER_API_KEY` | *(empty)* | Optional – reserved for future Elsevier Scopus integration |

All API keys are optional. The agent works fully without any keys using free public APIs.

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
│                           #   NEW: --download, --kb-dir flags
├── agent.py                # Orchestrate sources, deduplicate, interleave, save JSON
├── config.py               # Settings (pydantic), DOI prefixes, topic/industry keywords
├── query_builder.py        # Query expansion: detects missing industry terms, builds QueryBundle
├── prompt_template.py      # Template engine: load/render/validate prompts.json templates
│
├── downloader.py           # NEW: async download engine (Unpaywall + web scraper)
│                           #      builds local knowledge-base corpus
├── download.py             # NEW: standalone CLI for download.py
│
├── prompts.json            # 13 pre-built templates (edit to improve search quality)
├── pyproject.toml          # Project metadata and pip dependencies (managed by uv)
├── .env.example            # Environment variable template — copy to .env and edit
├── .env                    # Your local API keys and settings (not committed)
│
├── sources/                # One module per data source
│   ├── base.py             # Article dataclass + BaseSource abstract class
│   ├── crossref.py         # CrossRef API — IEEE, ScienceDirect, T&F, MDPI, Springer, ACS, Wiley
│   ├── semantic_scholar.py # Semantic Scholar Graph API (free, 1 rps)
│   ├── medium.py           # Medium RSS feeds (12 manufacturing tags)
│   └── slideshare.py       # SlideShare HTML scraper (industry presentations)
│
├── outputs/                # Auto-created; stores all JSON result files
│   └── YYYYMMDD_HHMMSS_<slug>.json
│
└── knowledge_base/         # Auto-created by downloader (default name)
    ├── index.json          # Master index: all downloaded articles + status
    └── papers/
        ├── IEEE/           # One folder per source
        ├── MDPI/
        ├── Medium/
        ├── SlideShare/
        └── .../
            └── <safe_id>/
                ├── metadata.json
                ├── paper.pdf    (if open-access PDF found)
                └── fulltext.txt (if web text scraped)
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
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `error 396` on `uv sync` | Cloud-synced drive (OneDrive) blocks hardlinks | Use `uv sync --link-mode=copy` |
| `UnicodeEncodeError` in terminal | Windows cp1252 console encoding | Avoid `→` `·` `–` in Rich output; use `->`, `\|`, `-` |
| Semantic Scholar rate limit warnings | Free tier is 1 rps shared | Normal — 429s are auto-retried. Set `SEMANTIC_SCHOLAR_API_KEY` in `.env` for 100 rps |
| SlideShare returns 0 results | Bot detection (HTTP 403) | Expected — SlideShare blocks scrapers intermittently. Use `--sources slideshare` and retry later |
| No Springer/ACS results for a query | Query terms too specific / not in CrossRef index | Broaden query or use `--verbose` to see per-prefix counts |
| Template key error | Missing required `--set` value | Run `--list-templates` to see required keys for the template |

---

*No API keys required. All sources use free public APIs or RSS feeds.*
