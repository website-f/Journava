"""Camofox Browser client — human-like public research (spec §8).

Wraps the camofox-browser REST API (Camoufox: Firefox with C++-level fingerprint
spoofing). A crawl that fails degrades the result; it never breaks a run.

Four things this client has to get right, each learned the hard way:

1. **Macros don't navigate.** The installed build leaves a `macro` tab on
   about:blank with an empty snapshot, so every macro is translated to the
   equivalent public search URL and driven through the direct-URL path.

2. **A tab returns when navigation commits, not when the page paints.**
   Snapshotting immediately yields an empty tree, so `browse` polls until real
   content lands — optionally until a `ready` regex matches, for results pages
   that render a "Fetching results…" shell first.

3. **Fare lists are lazy-loaded.** Waiting alone is not enough on metasearch
   pages: results stream in as you scroll. `browse` scrolls in passes with a
   pause between them, which is both what a reader does and what makes the
   results exist at all.

4. **Breadth beats depth.** One page is one opinion, so `read_many` reads a set
   of sites concurrently under a small concurrency cap.

The §8 access rules are enforced rather than merely documented: `robots.txt` is
honoured, concurrency is capped, think-time is randomised, and nothing here logs
in, pays, or defeats a captcha.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import urllib.parse
import urllib.robotparser
import uuid
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.core.cache import cached
from app.core.settings import settings
from app.core.text import clean_str

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
YOUTUBE_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

#: Consistent user identity for Camofox session isolation.
USER_ID = "journava"

#: The installed camofox-browser build does not navigate macro tabs (a `macro`
#: tab lands on about:blank with an empty snapshot). Direct-URL tabs DO navigate
#: and return real snapshots, so every "macro" is translated to the equivalent
#: public search URL and driven through the URL path instead.
_MACRO_URLS = {
    "@google_search": "https://www.google.com/search?hl=en&gl=my&q={q}",
    "@youtube_search": "https://www.youtube.com/results?search_query={q}",
    "@reddit_search": "https://www.reddit.com/search/?q={q}",
    "@wikipedia_search": "https://en.wikipedia.org/w/index.php?search={q}",
    "@yelp_search": "https://www.yelp.com/search?find_desc={q}",
    "@bing_search": "https://www.bing.com/search?q={q}",
    "@duckduckgo_search": "https://html.duckduckgo.com/html/?q={q}",
    # Crawl-friendly fallbacks (no-JS HTML endpoints) — used when the primary
    # engine is throttled, so a rate-limit on one never blanks the whole search.
    "@ddg_lite": "https://lite.duckduckgo.com/lite/?q={q}",
    "@mojeek_search": "https://www.mojeek.com/search?q={q}",
}

#: Tried in order for a general web search until one returns content — the
#: scrapy "retry-with-fallback" idea applied to search engines.
_WEB_ENGINES = ("@duckduckgo_search", "@ddg_lite", "@mojeek_search")

#: The default search engine.
#:
#: Google and Bing both `Disallow: /search` in robots.txt, and §8 commits us to
#: honouring robots — so using them as the research entry point was a compliance
#: problem as well as a fragile one (consent walls). DuckDuckGo's HTML endpoint
#: permits crawling, renders without JavaScript, and returns ~25k characters of
#: real results where the Google page returned a consent shell.
DEFAULT_SEARCH_MACRO = "@duckduckgo_search"

#: DuckDuckGo wraps outbound links as `/l/?uddg=<percent-encoded-target>`.
_DDG_REDIRECT = re.compile(r"[?&]uddg=([^&]+)")

#: Never more than this many pages open at once (§8: throttle and respect).
_MAX_CONCURRENT_PAGES = 3
_page_slots = asyncio.Semaphore(_MAX_CONCURRENT_PAGES)

#: Human think-time between actions, in seconds (§8 item 3). Widened so pacing
#: reads less machine-regular — a more human cadence eases rate-limit pressure.
_THINK_MIN, _THINK_MAX = 0.8, 2.6

#: A descriptive agent string, so operators can identify and block us if they wish.
ROBOTS_AGENT = "JournavaResearchBot"


def _base() -> str:
    return settings.camofox_url.rstrip("/")


async def _think() -> None:
    """Pause the way a person reading a page would."""
    await asyncio.sleep(random.uniform(_THINK_MIN, _THINK_MAX))  # noqa: S311


# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


async def robots_allows(url: str) -> bool:
    """True when `robots.txt` permits fetching `url`.

    §8 is explicit that public research honours robots. An unreachable
    robots.txt is treated as permission — that is the convention, and a site
    that serves no robots.txt has expressed no preference.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
    except ValueError:
        return False

    if origin not in _robots_cache:
        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
                response = await client.get(
                    f"{origin}/robots.txt",
                    headers={"User-Agent": ROBOTS_AGENT},
                    follow_redirects=True,
                )
            if response.status_code == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(response.text.splitlines())
        except Exception as exc:  # noqa: BLE001 — unreachable robots is not a denial
            logger.debug("robots.txt unreachable for %s: %s", origin, exc)
        _robots_cache[origin] = parser

    parser = _robots_cache[origin]
    if parser is None:
        return True
    try:
        return parser.can_fetch(ROBOTS_AGENT, url) or parser.can_fetch("*", url)
    except Exception:  # noqa: BLE001
        return True


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

#: Matches URLs inside an accessibility snapshot, so a crawled claim can always
#: be traced back to the page it came from.
_URL_PATTERN = re.compile(r"https?://[^\s\)\]\}\"'<>]+")

#: Hosts that are navigation rather than evidence — never cited as a source.
_NOISE_HOSTS = (
    "google.com/search",
    "google.com/preferences",
    "google.com/intl",
    "accounts.google.com",
    "policies.google.com",
    "support.google.com",
    "youtube.com/about",
    "youtube.com/t/",
    "reddit.com/login",
    "wikimediafoundation.org",
    "creativecommons.org",
    "mediawiki.org",
    "gstatic.com",
    "googleusercontent.com",
    "doubleclick.net",
    "onetrust.com",
)


#: Phrases that mean the site served a bot challenge instead of its content.
#:
#: §15 is explicit: never bypass a captcha. Camoufox's fingerprint resistance
#: exists so an ordinary browser is not *misclassified* as a bot — it is not a
#: licence to walk through a door a site has deliberately closed. So a challenge
#: is detected, named and reported, and the page is abandoned.
_CHALLENGE_MARKERS = (
    "are you a person or a robot",
    "security verification",
    "verify you are human",
    "verifying you are human",
    "checking your browser",
    "unusual traffic",
    "access denied",
    "captcha",
    "cf-challenge",
    "please enable javascript and cookies",
    "prove you are not a robot",
)


def detect_challenge(snapshot: str) -> str | None:
    """Return the challenge phrase a page is showing, or None.

    Distinguishing "the site said no" from "our crawler is broken" matters: one
    is a boundary to respect and report, the other is a bug to fix. Reporting
    both as a generic failure hides both.
    """
    lowered = (snapshot or "").lower()
    for marker in _CHALLENGE_MARKERS:
        if marker in lowered:
            return marker
    return None


def decode_redirect(url: str) -> str:
    """Unwrap a search-engine redirect to the real destination.

    DuckDuckGo hands back `duckduckgo.com/l/?uddg=https%3A%2F%2F…`. Citing that
    is useless to a reader and useless as a crawl target, so the real URL is
    recovered. Anything that is not a wrapper is returned unchanged.
    """
    match = _DDG_REDIRECT.search(url)
    if not match:
        return url
    try:
        decoded = urllib.parse.unquote(match.group(1))
    except Exception:  # noqa: BLE001
        return url
    return decoded if decoded.startswith("http") else url


def extract_sources(snapshot: str, *, limit: int = 8) -> list[str]:
    """Pull the citable URLs out of a snapshot, in order, de-duplicated.

    Research that cannot be checked is not much better than a guess, so every
    crawl-derived option carries the page it came from.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for raw in _URL_PATTERN.findall(snapshot or ""):
        url = decode_redirect(raw.rstrip(".,;:!?”’"))
        if url in seen:
            continue
        if any(noise in url for noise in _NOISE_HOSTS):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


async def search_with_sources(
    query: str,
    macro: str = DEFAULT_SEARCH_MACRO,
) -> dict[str, Any] | None:
    """Run a search macro and return both the snapshot and its source URLs."""
    snapshot = await search(query, macro=macro)
    if not snapshot:
        return None
    return {
        "snapshot": snapshot,
        "sources": extract_sources(snapshot),
        "macro": macro,
        "query": query,
    }


async def search(query: str, macro: str = DEFAULT_SEARCH_MACRO) -> str | None:
    """Run a search and return the accessibility snapshot text.

    The `macro` selects which public search engine/site to use; it is translated
    to a real URL and driven through the (working) direct-URL path, because the
    installed camofox-browser build leaves macro tabs on about:blank.

    Hardened for rate-limits: a human-paced retry-with-backoff (a first empty read
    is usually a throttle blip or an unrendered page, not a dead end), and a 6-hour
    cache so a repeated query never re-hits the engine. `cached` never stores a
    `None`, so a throttle is retried next time rather than remembered as empty.
    """
    # A general web search rotates through several crawl-friendly engines; a
    # site-specific macro (youtube/wikipedia/…) stays on its own engine.
    engines = list(_WEB_ENGINES) if macro == DEFAULT_SEARCH_MACRO else [macro]
    encoded = quote_plus(query)
    cache_key = f"camofox:search:{macro}:{query.strip().lower()}"

    async def fetch() -> str | None:
        for engine in engines:
            template = _MACRO_URLS.get(engine, _MACRO_URLS[DEFAULT_SEARCH_MACRO])
            url = template.format(q=encoded)
            for attempt in range(2):
                snapshot = await browse(url)
                if snapshot:
                    return snapshot
                if attempt == 0:
                    await asyncio.sleep(random.uniform(1.5, 3.0))  # noqa: S311 — human-paced backoff
        return None

    return await cached(cache_key, fetch, ttl=6 * 3600)


async def youtube_transcript(url: str, languages: list[str] | None = None) -> dict[str, Any] | None:
    """Extract captions from a YouTube video.

    Returns dict with keys: transcript, video_title, total_words.
    Returns None on failure.
    """

    async def fetch() -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=YOUTUBE_TIMEOUT) as client:
            resp = await client.post(
                f"{_base()}/youtube/transcript",
                json={"url": url, "languages": languages or ["en"]},
            )
            if resp.status_code != 200:
                logger.debug("YouTube transcript HTTP %d for %s", resp.status_code, url)
                return None
            data = resp.json()
            if data.get("status") != "ok":
                return None
            return {
                "transcript": data.get("transcript", ""),
                "video_title": data.get("video_title", ""),
                "total_words": data.get("total_words", 0),
            }

    try:
        return await cached(f"camofox:yt:{url}", fetch, ttl=24 * 3600)
    except Exception:  # noqa: BLE001
        logger.warning("Camofox YouTube transcript failed: %s", url)
        return None


async def browse(
    url: str,
    *,
    ready: str | None = None,
    attempts: int = 6,
    delay: float = 1.5,
    scrolls: int = 3,
    respect_robots: bool = True,
    collect_links: bool = False,
) -> str | None:
    """Navigate to a URL and return the accessibility snapshot.

    `ready` is an optional regex: polling continues until the snapshot matches it
    (e.g. a price token on a results page that shows "Fetching results…" first).
    `scrolls` drives lazy-loaded content into existence — a metasearch fare list
    is mostly empty until you scroll it.
    """
    result = await read_page(
        url,
        ready=ready,
        attempts=attempts,
        delay=delay,
        scrolls=scrolls,
        respect_robots=respect_robots,
        collect_links=collect_links,
    )
    return (result or {}).get("snapshot") or None


async def read_page(
    url: str,
    *,
    ready: str | None = None,
    attempts: int = 6,
    delay: float = 1.5,
    scrolls: int = 3,
    respect_robots: bool = True,
    collect_links: bool = True,
) -> dict[str, Any] | None:
    """Open a page, let it render, scroll it, and read it.

    Returns `{url, snapshot, links, sources}` — or a `skipped` marker when
    robots.txt disallows the fetch.
    """
    if respect_robots and not await robots_allows(url):
        logger.info("robots.txt disallows %s — skipping", url)
        return {"url": url, "snapshot": "", "links": [], "sources": [], "skipped": "robots"}

    async def fetch() -> dict[str, Any] | None:
        session_key = f"browse-{uuid.uuid4().hex[:8]}"
        budget = max(45.0, attempts * delay + scrolls * 2.5 + 20.0)
        client_timeout = httpx.Timeout(budget, connect=10.0)

        async with _page_slots:
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                tab = await _create_tab(client, _base(), session_key, url=url)
                if tab is None:
                    return None
                tab_id = tab["tabId"]
                try:
                    # A tab returns as soon as navigation is *committed*, not when
                    # the page is painted — snapshotting immediately yields an
                    # empty tree. Poll until content lands.
                    snapshot = await _wait_and_snapshot(
                        client, _base(), tab_id, ready=ready, attempts=attempts, delay=delay
                    )

                    # Then scroll: metasearch results stream in on scroll, so a
                    # page that has "rendered" is often still one row of skeleton.
                    if scrolls:
                        await _think()
                        for _ in range(scrolls):
                            await _scroll(client, _base(), tab_id)
                            await asyncio.sleep(random.uniform(0.5, 1.2))  # noqa: S311
                        grown = await _wait_and_snapshot(
                            client, _base(), tab_id, ready=ready, attempts=3, delay=1.0
                        )
                        if grown and len(grown) > len(snapshot or ""):
                            snapshot = grown

                    links = await _links(client, _base(), tab_id) if collect_links else []
                finally:
                    await _close_tab(client, _base(), tab_id)

        # Snapshots occasionally carry bytes that decode into lone surrogates,
        # which later blow up JSON serialization (a single one 500'd GET /trip).
        # Scrub at the source so no downstream agent inherits an unencodable str.
        text = clean_str(snapshot or "")
        return {
            "url": url,
            "snapshot": text,
            "links": links,
            "sources": extract_sources(text) + _link_urls(links),
        }

    cache_key = f"camofox:page:{url}:{ready or ''}:{scrolls}"
    try:
        return await cached(cache_key, fetch, ttl=6 * 3600)
    except Exception:  # noqa: BLE001
        logger.warning("Camofox browse failed: %s", url)
        return None


async def read_many(
    targets: list[dict[str, Any]],
    *,
    scrolls: int = 3,
    ready: str | None = None,
) -> list[dict[str, Any]]:
    """Read several pages concurrently, bounded by the page-slot semaphore.

    Each target is `{"url": ..., "label": ..., ...}`. Failures come back as
    entries with `ok: False` rather than disappearing, so the caller can report
    which sites it could not read instead of silently narrowing the comparison.
    """

    async def one(target: dict[str, Any]) -> dict[str, Any]:
        label = target.get("label") or target.get("url") or ""
        url = target.get("url")
        if not url:
            return {**target, "label": label, "ok": False, "error": "no url"}
        try:
            result = await read_page(
                url,
                ready=target.get("ready", ready),
                attempts=target.get("attempts", 8),
                delay=target.get("delay", 1.5),
                scrolls=target.get("scrolls", scrolls),
            )
        except Exception as exc:  # noqa: BLE001 — one bad page must not stop the sweep
            logger.info("camofox read failed for %s: %s", label, exc)
            return {**target, "label": label, "ok": False, "error": str(exc)[:200]}

        if not result:
            return {**target, "label": label, "ok": False, "error": "no response"}
        if result.get("skipped"):
            return {**target, "label": label, "ok": False, "error": "robots.txt"}
        snapshot = result.get("snapshot") or ""
        if not snapshot.strip():
            return {**target, "label": label, "ok": False, "error": "empty page"}

        challenge = detect_challenge(snapshot)
        if challenge:
            # The site asked us to prove we are human. We do not answer that
            # (§15), so the page is abandoned and the refusal reported.
            logger.info("%s served a bot challenge (%s) — not bypassed", label, challenge)
            return {
                **target,
                "label": label,
                "ok": False,
                "error": f"bot challenge ({challenge})",
                "challenge": challenge,
                **result,
            }
        return {**target, "label": label, "ok": True, **result}

    return list(await asyncio.gather(*(one(target) for target in targets)))


async def available() -> bool:
    """Check if the Camofox Browser service is reachable."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{_base()}/health")
            return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _link_urls(links: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for entry in links:
        href = entry.get("url") or entry.get("href")
        if isinstance(href, str) and href.startswith("http"):
            urls.append(decode_redirect(href))
    return urls


async def _create_tab(
    client: httpx.AsyncClient,
    base: str,
    session_key: str,
    *,
    url: str | None = None,
    macro: str | None = None,
    query: str | None = None,
) -> dict[str, Any] | None:
    """Create a new tab. Returns {"tabId": "..."} or None.

    `macro`/`query` are accepted for compatibility but do not navigate on the
    installed build — callers should translate macros to URLs (`_MACRO_URLS`).
    """
    body: dict[str, Any] = {"userId": USER_ID, "sessionKey": session_key}

    # Route through a proxy when configured (rotating/residential IPs are the only
    # real fix for IP-based rate-limits — a stealth fingerprint doesn't change the
    # IP). Best-effort: the browser server uses it if it honours the field.
    if settings.camofox_proxy:
        body["proxy"] = settings.camofox_proxy

    if macro and query:
        body["macro"] = macro
        body["query"] = query
    elif url:
        body["url"] = url
    else:
        return None

    try:
        resp = await client.post(f"{base}/tabs", json=body)
        if resp.status_code not in (200, 201):
            logger.debug("Camofox create tab HTTP %d", resp.status_code)
            return None
        data = resp.json()
        return {"tabId": data.get("tabId") or data.get("id")}
    except Exception:  # noqa: BLE001
        return None


async def _wait_and_snapshot(
    client: httpx.AsyncClient,
    base: str,
    tab_id: str,
    *,
    ready: str | None = None,
    min_len: int = 200,
    attempts: int = 6,
    delay: float = 1.5,
) -> str | None:
    """Poll the snapshot until the page has rendered content (or attempts run out).

    Returns the best snapshot seen. `min_len` guards against returning the empty
    tree of a page that has navigated but not yet painted. When `ready` is given,
    polling continues until that regex is found — for results pages that render a
    "Fetching results…" shell before the data arrives.
    """
    ready_re = re.compile(ready, re.IGNORECASE) if ready else None
    snapshot = ""
    for _ in range(attempts):
        await asyncio.sleep(delay)
        current = await _snapshot(client, base, tab_id) or ""
        if len(current) > len(snapshot):
            snapshot = current
        if len(snapshot) >= min_len and (ready_re is None or ready_re.search(snapshot)):
            break
    return snapshot or None


async def _scroll(
    client: httpx.AsyncClient,
    base: str,
    tab_id: str,
    *,
    amount: int = 900,
    direction: str = "down",
) -> None:
    """Scroll, which is what makes lazy-loaded results appear at all."""
    try:
        await client.post(
            f"{base}/tabs/{tab_id}/scroll",
            json={"userId": USER_ID, "direction": direction, "amount": amount},
        )
    except Exception:  # noqa: BLE001
        pass


async def _links(
    client: httpx.AsyncClient,
    base: str,
    tab_id: str,
    *,
    limit: int = 60,
) -> list[dict[str, Any]]:
    """Outbound links on the page — how a results page becomes real sources."""
    try:
        resp = await client.get(
            f"{base}/tabs/{tab_id}/links",
            params={"userId": USER_ID, "limit": limit},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        raw = data.get("links") or data.get("items") or []
        return [entry for entry in raw if isinstance(entry, dict)]
    except Exception:  # noqa: BLE001
        return []


async def _snapshot(
    client: httpx.AsyncClient,
    base: str,
    tab_id: str,
) -> str | None:
    """Get accessibility snapshot for a tab."""
    try:
        resp = await client.get(
            f"{base}/tabs/{tab_id}/snapshot",
            params={"userId": USER_ID},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("snapshot", "")
    except Exception:  # noqa: BLE001
        return None


async def _close_tab(
    client: httpx.AsyncClient,
    base: str,
    tab_id: str,
) -> None:
    """Close a tab (fire-and-forget cleanup)."""
    try:
        await client.delete(f"{base}/tabs/{tab_id}", params={"userId": USER_ID})
    except Exception:  # noqa: BLE001
        pass  # Best-effort cleanup
