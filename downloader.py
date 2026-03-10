"""
downloader.py – Full-text downloader and local knowledge-base corpus builder.

Strategies by source
--------------------
Medium / SlideShare      : Scrape full article / slide text via httpx + BeautifulSoup.
MDPI (doi 10.3390)       : Always open-access; retrieve PDF via Unpaywall or direct fetch.
IEEE / ScienceDirect /
  Springer / ACS / Wiley
  / TaylorFrancis        : Paywalled; query Unpaywall for a legal open-access copy.
                           If none found, save metadata + abstract only.
Academic (Semantic Scholar): Try Unpaywall on DOI; fall back to direct URL text scrape.

Corpus layout
-------------
<kb_dir>/
  index.json                 # master index keyed by "doi:<doi>" or "url:<url>"
  papers/
    <Source>/
      <safe_id>/
        metadata.json        # article metadata + download status
        paper.pdf            # academic PDF (if open-access copy found)
        fulltext.txt         # web-article text (Medium, SlideShare, etc.)

Unpaywall API
-------------
GET https://api.unpaywall.org/v2/<doi>?email=<email>
Returns best open-access PDF URL if any. Free; only needs an email address.
No API key required.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Literal

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
DownloadStatus = Literal["pdf", "fulltext", "metadata_only", "failed", "skipped"]

# ---------------------------------------------------------------------------
# HTTP headers – browser-like UA so Medium / SlideShare don't block us
# ---------------------------------------------------------------------------
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
}

# Sources where full text is publicly accessible via HTTP scrape
_SCRAPE_SOURCES = {"Medium", "SlideShare"}

# Sources that are almost always paywalled (try Unpaywall before giving up)
_PAYWALL_SOURCES = {"IEEE", "ScienceDirect", "TaylorFrancis", "Springer", "ACS", "Wiley"}

# MDPI DOI prefix – always open access
_MDPI_PREFIX = "10.3390"


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _safe_id(doi: str, url: str) -> str:
    """Build a filesystem-safe directory name for an article (max ~80 chars)."""
    key  = doi if doi else url
    safe = re.sub(r"[^\w\-.]", "_", key)[:70]
    h    = hashlib.md5(key.encode()).hexdigest()[:8]
    return f"{safe}_{h}"


def _dedup_key(article: dict) -> str:
    """Primary deduplication key: 'doi:<doi>' or 'url:<url>'."""
    doi = (article.get("doi") or "").strip()
    url = (article.get("url") or "").strip()
    return f"doi:{doi.lower()}" if doi else f"url:{url.lower()}"


def _load_index(kb_dir: Path) -> dict:
    idx_file = kb_dir / "index.json"
    if idx_file.exists():
        try:
            return json.loads(idx_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_index(kb_dir: Path, index: dict) -> None:
    kb_dir.mkdir(parents=True, exist_ok=True)
    (kb_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

async def _try_unpaywall(doi: str, email: str, client: httpx.AsyncClient) -> str | None:
    """
    Query the Unpaywall API for a free, legal PDF URL for the given DOI.
    Returns the URL string or None if no open-access copy exists.

    Unpaywall is a non-profit (impactstory.org) that indexes legal OA copies
    of 30 M+ academic articles. The API is free; just send any valid email.
    """
    if not doi:
        return None
    endpoint = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    try:
        resp = await client.get(endpoint, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # best_oa_location is Unpaywall's top recommendation
            best    = data.get("best_oa_location") or {}
            pdf_url = best.get("url_for_pdf") or best.get("url")
            if pdf_url:
                return pdf_url
            # Fall back to scanning all OA locations
            for loc in data.get("oa_locations", []):
                if loc.get("url_for_pdf"):
                    return loc["url_for_pdf"]
        return None
    except Exception as exc:
        logger.debug("Unpaywall lookup failed for DOI %s: %s", doi, exc)
        return None


async def _download_pdf(pdf_url: str, client: httpx.AsyncClient) -> bytes | None:
    """
    Fetch a PDF from a URL.  Returns raw bytes when the response is a valid
    PDF (magic-byte check), or None on any error / non-PDF response.
    """
    try:
        resp = await client.get(pdf_url, timeout=40, follow_redirects=True)
        if resp.status_code == 200:
            content = resp.content
            if content[:5] in (b"%PDF-", b"%pdf-") or b"%PDF" in content[:20]:
                return content
        return None
    except Exception as exc:
        logger.debug("PDF download failed from %s: %s", pdf_url, exc)
        return None


async def _fetch_webpage_text(url: str, client: httpx.AsyncClient) -> str | None:
    """
    Fetch a web page and extract its main article text.
    Strips scripts / nav / boilerplate; returns plain text (up to 50 000 chars)
    or None if the page cannot be fetched or is too short to be useful.
    """
    try:
        resp = await client.get(url, timeout=25, follow_redirects=True)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Discard boilerplate tags
        for tag in soup(
            ["script", "style", "nav", "header", "footer",
             "aside", "noscript", "form", "iframe", "svg"]
        ):
            tag.decompose()

        # Try successively broader selectors for the main content block
        selectors = [
            "article",
            "main",
            '[role="main"]',
            ".post-content",
            ".article-content",
            ".entry-content",
            ".article-body",
            "#article-body",
            "#content",
            ".content",
            "body",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 300:
                    return text[:50_000]

        return None
    except Exception as exc:
        logger.debug("Webpage fetch failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Per-article download worker
# ---------------------------------------------------------------------------

async def _download_one(
    article: dict,
    kb_dir: Path,
    email: str,
    client: httpx.AsyncClient,
    index: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    """
    Download a single article and persist it to the corpus.
    Returns the updated index-entry dict.
    """
    doi    = (article.get("doi")    or "").strip()
    url    = (article.get("url")    or "").strip()
    source = (article.get("source") or "Unknown")
    title  = (article.get("title")  or "(no title)")[:80]

    key = _dedup_key(article)

    # Already fully downloaded in a previous run – skip
    if key in index and index[key].get("download_status") in ("pdf", "fulltext"):
        logger.info("  SKIP (already in corpus): %s", title)
        return {**index[key], "download_status": "skipped"}

    # Prepare article directory inside the corpus
    article_id  = _safe_id(doi, url)
    article_dir = kb_dir / "papers" / source / article_id
    article_dir.mkdir(parents=True, exist_ok=True)

    entry: dict = {
        **{k: article.get(k, "")
           for k in ("title", "source", "url", "doi", "year", "authors", "abstract")},
        "dedup_key":       key,
        "download_status": "metadata_only",
        "downloaded_at":   None,
        "local_path":      str(article_dir.relative_to(kb_dir)),
        "oa_url":          None,
        "error":           None,
    }

    async with semaphore:
        try:
            # ── Web-scrapeable sources: Medium & SlideShare ─────────────────
            if source in _SCRAPE_SOURCES:
                text = await _fetch_webpage_text(url, client)
                if text:
                    (article_dir / "fulltext.txt").write_text(text, encoding="utf-8")
                    entry["download_status"] = "fulltext"
                    entry["downloaded_at"]   = time.strftime("%Y-%m-%dT%H:%M:%S")
                    logger.info("  [FULLTEXT] %s", title)
                else:
                    entry["download_status"] = "failed"
                    entry["error"]           = "Scrape returned no usable text"
                    logger.info("  [FAILED]   %s (scrape empty)", title)

            # ── MDPI: always open-access; use Unpaywall for the PDF link ────
            elif source == "MDPI" or doi.startswith(_MDPI_PREFIX):
                oa_url = await _try_unpaywall(doi, email, client)
                entry["oa_url"] = oa_url
                if oa_url:
                    pdf_bytes = await _download_pdf(oa_url, client)
                    if pdf_bytes:
                        (article_dir / "paper.pdf").write_bytes(pdf_bytes)
                        entry["download_status"] = "pdf"
                        entry["downloaded_at"]   = time.strftime("%Y-%m-%dT%H:%M:%S")
                        logger.info("  [PDF]      %s", title)
                    else:
                        logger.info(
                            "  [META+OA]  %s (OA link found; PDF not directly downloadable)", title
                        )
                else:
                    logger.info("  [META]     %s (MDPI – Unpaywall found no OA copy)", title)

            # ── Paywalled academic publishers: query Unpaywall ──────────────
            elif source in _PAYWALL_SOURCES or doi:
                oa_url = await _try_unpaywall(doi, email, client)
                entry["oa_url"] = oa_url
                if oa_url:
                    pdf_bytes = await _download_pdf(oa_url, client)
                    if pdf_bytes:
                        (article_dir / "paper.pdf").write_bytes(pdf_bytes)
                        entry["download_status"] = "pdf"
                        entry["downloaded_at"]   = time.strftime("%Y-%m-%dT%H:%M:%S")
                        logger.info("  [PDF-OA]   %s", title)
                    else:
                        logger.info(
                            "  [META+OA]  %s (OA URL found; PDF not downloadable – "
                            "may require institution login)", title
                        )
                else:
                    logger.info("  [META]     %s (paywalled; no open-access copy found)", title)

            # ── Academic (Semantic Scholar) ─────────────────────────────────
            elif source == "Academic":
                # Prefer Unpaywall on DOI if available
                oa_url = await _try_unpaywall(doi, email, client) if doi else None
                entry["oa_url"] = oa_url
                if oa_url:
                    pdf_bytes = await _download_pdf(oa_url, client)
                    if pdf_bytes:
                        (article_dir / "paper.pdf").write_bytes(pdf_bytes)
                        entry["download_status"] = "pdf"
                        entry["downloaded_at"]   = time.strftime("%Y-%m-%dT%H:%M:%S")
                        logger.info("  [PDF-OA]   %s", title)
                        # Proceed to next article
                    else:
                        # OA URL found but not a downloadable PDF – try scraping
                        text = await _fetch_webpage_text(oa_url, client)
                        if text and len(text) > 300:
                            (article_dir / "fulltext.txt").write_text(text, encoding="utf-8")
                            entry["download_status"] = "fulltext"
                            entry["downloaded_at"]   = time.strftime("%Y-%m-%dT%H:%M:%S")
                            logger.info("  [FULLTEXT] %s (from OA URL)", title)
                        else:
                            logger.info("  [META+OA]  %s (OA URL found; no downloadable content)", title)
                else:
                    # No Unpaywall hit – try scraping the landing page
                    text = await _fetch_webpage_text(url, client)
                    if text and len(text) > 300:
                        (article_dir / "fulltext.txt").write_text(text, encoding="utf-8")
                        entry["download_status"] = "fulltext"
                        entry["downloaded_at"]   = time.strftime("%Y-%m-%dT%H:%M:%S")
                        logger.info("  [FULLTEXT] %s (landing-page scrape)", title)
                    else:
                        logger.info("  [META]     %s (Academic; no open-access content)", title)

            else:
                logger.info("  [META]     %s (unknown source: %s)", title, source)

        except Exception as exc:
            logger.error("  [ERROR]    %s: %s", title, exc)
            entry["download_status"] = "failed"
            entry["error"]           = str(exc)

    # Always persist metadata.json regardless of download outcome
    (article_dir / "metadata.json").write_text(
        json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return entry


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def download_corpus(
    articles: list[dict],
    kb_dir: str | Path = "knowledge_base",
    email: str = "research-agent@example.com",
    max_concurrent: int = 4,
    skip_sources: list[str] | None = None,
) -> dict:
    """
    Download full text / PDFs for a list of article dicts and build a local
    knowledge-base corpus.

    Parameters
    ----------
    articles       : List of article dicts (as saved by agent.save_results).
    kb_dir         : Root directory for the local corpus.
    email          : Any valid email – sent to Unpaywall as required by their API.
    max_concurrent : Maximum simultaneous HTTP connections.
    skip_sources   : Source names to skip entirely (e.g. ["SlideShare"]).

    Returns
    -------
    dict
        Summary counts: {total, pdf, fulltext, metadata_only, failed, skipped}

    Notes
    -----
    - Only legally accessible copies are downloaded (Unpaywall OA links,
      publicly accessible web pages).  Paywall content is never bypassed.
    - Incremental: articles already in the corpus (pdf / fulltext) are skipped.
    - The master index (<kb_dir>/index.json) is updated after every run.
    """
    kb_dir = Path(kb_dir)
    kb_dir.mkdir(parents=True, exist_ok=True)

    skip_set   = set(skip_sources or [])
    to_process = [a for a in articles if a.get("source", "") not in skip_set]

    index     = _load_index(kb_dir)
    semaphore = asyncio.Semaphore(max_concurrent)

    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    async with httpx.AsyncClient(
        headers=_HEADERS, limits=limits, follow_redirects=True
    ) as client:
        tasks = [
            _download_one(a, kb_dir, email, client, index, semaphore)
            for a in to_process
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge successful entries back into the master index
    for entry in results:
        if isinstance(entry, dict):
            key = entry.get("dedup_key")
            if key and entry.get("download_status") != "skipped":
                index[key] = entry

    _save_index(kb_dir, index)

    # Tally outcome counts
    counts: dict[str, int] = {
        "total":         len(to_process),
        "pdf":           0,
        "fulltext":      0,
        "metadata_only": 0,
        "failed":        0,
        "skipped":       0,
    }
    for entry in results:
        if isinstance(entry, dict):
            status = entry.get("download_status", "failed")
            counts[status] = counts.get(status, 0) + 1
        elif isinstance(entry, Exception):
            counts["failed"] += 1

    return counts
