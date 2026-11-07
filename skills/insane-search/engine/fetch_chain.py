"""Single entrypoint: insane-search generic fetch chain.

    from insane_search.engine import fetch
    result = fetch("https://example.com/path", success_selectors=["article"])

Public contract:
  * One function: `fetch(url, ...) -> FetchResult`.
  * Internal structure preserved as explicit phases so tests & debug logs
    can target each stage: probe → validate → detect → plan → execute → report.
  * `FetchResult.trace` exposes every attempt (transform × impersonate ×
    referer × executor) — callers can diagnose without re-running.

v2 scheduler (multi-AI review 2026-06-21):
  * `_build_plan` materializes the whole grid then orders it for DIVERSITY —
    one representative per TLS family across both URL transforms first, so a
    small attempt budget still touches every family/transform instead of
    burning out on the Safari family.
  * `tls_impersonate_avoid` entries are DEPRIORITIZED (moved last), never
    deleted — they are still attempted in exhaustive mode.
  * `max_attempts=None` (new default) means EXHAUSTIVE — run the full plan,
    honouring R6. A numeric cap is a *budget*, and exhaustion vs budget vs
    early-terminal is reported via `stop_reason` / `grid_exhausted`.
  * Jitter sleeps only on a CONTINUING (failed) attempt, never before a
    successful return.
  * `SUSPECT_OK` (abck unresolved / soft block) is NON-terminal: kept as
    best-effort, but the grid keeps searching for real proof.

No site-specific branching. Site knowledge enters only via:
  * `success_selectors` (caller-supplied positive proof)
  * `user_hint` (optional runtime hints; never persisted by this module)
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .content_safety import ContentSafetyReport, analyze_untrusted_content, wrap_untrusted_content
from .validators import Verdict, validate, TERMINAL_NONSUCCESS
from .waf_detector import detect, _load_profiles, load_profile, last_load_error
from .url_transforms import iter_transformed


_OK_VALUES = (Verdict.STRONG_OK.value, Verdict.WEAK_OK.value)
# Role (a) — "stop the TLS diversity grid; more curl attempts cannot help".
# 429 IS included here on purpose: hammering the grid only deepens rate-limiting.
_TERMINAL_NONSUCCESS_VALUES = frozenset(v.value for v in TERMINAL_NONSUCCESS)
# 인증과 없는 문서는 브라우저로도 해결하지 않아요.
_BROWSER_FUTILE_VALUES = frozenset({
    Verdict.AUTH_REQUIRED.value, Verdict.NOT_FOUND.value,
})


# --- Referer strategies (name → function of original URL) --------------------
def _self_root(url: str) -> str:
    from urllib.parse import urlsplit
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}/"


REFERER_STRATEGIES = {
    "self_root": _self_root,
    "google_search": lambda _url: "https://www.google.com/",
    "none": lambda _url: "",
}


# --- Attempt & result schema -------------------------------------------------
@dataclass
class Attempt:
    phase: str                       # HTTP 수집 단계를 기록해요.
    executor: str                    # HTTP 실행기를 기록해요.
    url: str
    url_transform: str               # original | mobile_subdomain | ...
    impersonate: Optional[str]       # safari | chrome | ... | None (non-curl)
    referer: str
    status: int = 0
    body_size: int = 0
    verdict: str = ""
    reasons: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FetchResult:
    ok: bool
    content: str = ""
    final_url: str = ""
    verdict: str = ""
    profile_used: Optional[str] = None
    trace: list[Attempt] = field(default_factory=list)
    summary: str = ""
    # v2 scheduler diagnostics
    planned_attempts: int = 0
    executed_attempts: int = 0
    grid_exhausted: bool = False
    stop_reason: str = ""
    untried_routes: list[str] = field(default_factory=list)
    needs_browser: bool = False
    content_trust: str = ""
    prompt_injection_risk: str = ""
    prompt_injection_signals: list[str] = field(default_factory=list)
    untrusted_content_boundary: dict[str, str] = field(default_factory=dict)
    # HTTP 본문의 PDF, JSON-LD 및 문서 추출 출처를 기록해요.
    extraction_quality: float = 0.0
    extraction_source: str = ""
    extraction_meta: dict = field(default_factory=dict)
    # M4 differential block classification (failure path only): comparing the
    # outcomes of the routes already tried tells the caller whether trying
    # harder can ever work. "" on success / insufficient signal;
    # "bot_detection" = routes disagree or a WAF/challenge signal → bypassable
    # (browser / more routes may help); "infra_or_auth" = every route uniformly
    # 401/404 → a real wall stealth cannot clear.
    block_class: str = ""

    def __post_init__(self) -> None:
        report = analyze_untrusted_content(self.content, source_url=self.final_url)
        if not self.content_trust:
            self.content_trust = report.content_trust
        if not self.prompt_injection_risk:
            self.prompt_injection_risk = report.prompt_injection_risk
        if not self.prompt_injection_signals:
            self.prompt_injection_signals = list(report.prompt_injection_signals)
        if not self.untrusted_content_boundary:
            self.untrusted_content_boundary = dict(report.untrusted_content_boundary)

    def to_untrusted_text(self) -> str:
        report = ContentSafetyReport(
            content_trust=self.content_trust,
            prompt_injection_risk=self.prompt_injection_risk,
            prompt_injection_signals=list(self.prompt_injection_signals),
            untrusted_content_boundary={
                "begin": self.untrusted_content_boundary["begin"],
                "end": self.untrusted_content_boundary["end"],
            },
        )
        return wrap_untrusted_content(self.content, report=report, source_url=self.final_url)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "final_url": self.final_url,
            "verdict": self.verdict,
            "profile_used": self.profile_used,
            "trace": [a.to_dict() for a in self.trace],
            "summary": self.summary,
            "content_length": len(self.content),
            "planned_attempts": self.planned_attempts,
            "executed_attempts": self.executed_attempts,
            "grid_exhausted": self.grid_exhausted,
            "stop_reason": self.stop_reason,
            "untried_routes": self.untried_routes,
            "needs_browser": self.needs_browser,
            "content_trust": self.content_trust,
            "prompt_injection_risk": self.prompt_injection_risk,
            "prompt_injection_signals": self.prompt_injection_signals,
            "untrusted_content_boundary": self.untrusted_content_boundary,
            "extraction_quality": self.extraction_quality,
            "extraction_source": self.extraction_source,
            "extraction_meta": self.extraction_meta,
            "block_class": self.block_class,
        }


# --- Content rescue extraction -----------------------------------------------
# Deliberately narrow scope: the raw body REMAINS `content` for ordinary HTML
# successes. A rescue path replaces it only where the raw body is unusable for
# an LLM, and only when the rescue demonstrably carries MORE text than the raw
# body's visible text — the gate that keeps a teaser (JSON-LD description)
# from beating a full article:
#   * PDF bodies (magic bytes / content-type, re-guarded) → pypdf text
#   * SPA shells whose visible text is thinner than their JSON-LD articleBody
# pypdf is an optional import; every path degrades to the raw text.
import io as _io
import json as _json
import re as _re

_PdfReader = None

# Optional: HTML→markdown (M1). When present, a raw-HTML success is converted
# to structure-preserving markdown (tables→pipe tables, <pre>/<code>→fences,
# headings/lists/links kept) so the LLM gets clean text instead of tag soup.
# Absent → the raw HTML is kept unchanged (graceful degradation).
try:
    import markdownify as _markdownify
except ImportError:
    _markdownify = None

# Optional: main-content extraction (M2). When present, resiliparse strips
# nav/footer/sidebars/ads and returns the article body as formatted plain text
# (lists/links/<pre> preserved). Absent → the raw HTML is kept (graceful).
try:
    from resiliparse.extract.html2text import extract_plain_text as _extract_plain_text
except ImportError:
    _extract_plain_text = None

_MAINCONTENT_MIN_CHARS = 200     # reject a near-empty extraction, keep raw

# Optional: pdfplumber (M3) — MIT, pure-Python (pdfminer.six). Better on
# multi-column layouts and tables than pypdf. Tried first; falls back to pypdf.
# pymupdf / pymupdf4llm are AGPL and must NOT be used here (would relicense the
# MIT plugin).
_pdfplumber = None
_pdf_extractors_loaded = False


def _load_pdf_extractors() -> None:
    """Load optional PDF dependencies once, only when a bounded PDF needs them."""
    global _PdfReader, _pdfplumber, _pdf_extractors_loaded
    if _pdf_extractors_loaded:
        return
    try:
        from pypdf import PdfReader as reader
        _PdfReader = reader
    except ImportError:
        _PdfReader = None
    try:
        import pdfplumber as plumber
        _pdfplumber = plumber
    except ImportError:
        _pdfplumber = None
    _pdf_extractors_loaded = True

_JSONLD_MIN_CHARS = 100          # an articleBody shorter than this is a teaser

# Parser-input ceilings. Every byte reaching a rescue parser is attacker
# controlled, so each parser gets a hard input bound and a bounded output —
# without these, a hostile page could feed multi-hundred-MB bodies into
# regex/JSON/PDF parsing on what is otherwise just a fetch.
_SCAN_LIMIT = 2_000_000          # chars of body the rescue regexes may scan
_JSONLD_MAX_BLOCKS = 10          # ld+json blocks parsed per page
_JSONLD_MAX_BLOB = 200_000       # chars of a single ld+json blob given to json.loads
_RESCUE_MAX_TEXT = 1_000_000     # chars any rescue path may return as content
_PDF_MAX_BYTES = 25 * 1024 * 1024  # PDF bodies above this are never parsed


def _quality_score(md: str) -> float:
    """Crude 0..1 extraction-quality heuristic: length + sentence density."""
    if not md:
        return 0.0
    length_s = min(len(md) / 3000.0, 1.0)
    sentences = len(_re.findall(r"[.!?。…]\s", md)) + 1
    words = max(len(md.split()), 1)
    struct_s = min(sentences / (words / 18.0 + 1), 1.0)
    return round(max(0.0, min(1.0, 0.6 * length_s + 0.4 * struct_s)), 2)


def _visible_text(html: str) -> str:
    """Body text after stripping script/style/markup — the length yardstick
    every rescue path must beat before it may replace the raw body."""
    t = _re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", html)
    t = _re.sub(r"(?s)<[^>]+>", " ", t)
    return _re.sub(r"\s+", " ", t).strip()


def _extract_json_ld_text(html: str) -> str:
    """Pull articleBody / description from <script type=application/ld+json>.

    Bounded: at most _JSONLD_MAX_BLOCKS blocks are parsed, a blob larger than
    _JSONLD_MAX_BLOB is skipped without json.loads, and the joined output is
    capped at _RESCUE_MAX_TEXT."""
    out: list[str] = []
    blocks = 0
    total = 0
    for m in _re.finditer(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, _re.I | _re.S):
        blocks += 1
        if blocks > _JSONLD_MAX_BLOCKS:
            break
        raw = m.group(1)
        if len(raw) > _JSONLD_MAX_BLOB:
            continue
        try:
            data = _json.loads(raw)
            if isinstance(data, list):
                data = data[0] if data else {}
            if isinstance(data, dict):
                t = (data.get("@type") or "")
                if t in ("Article", "NewsArticle", "BlogPosting") or "articleBody" in data:
                    body = data.get("articleBody") or data.get("description") or ""
                    if isinstance(body, str) and body:
                        take = body[:_RESCUE_MAX_TEXT - total]
                        if take:
                            out.append(take)
                            total += len(take)
                        if total >= _RESCUE_MAX_TEXT:
                            break
        except Exception:
            pass
    return "\n\n".join(out)


def _extract_pdf_pdfplumber(body: bytes) -> tuple[str, str]:
    """(title, text) via pdfplumber, or ("", "") on failure / no text layer.
    Same bounds as the pypdf path: ≤80 pages, text capped at _RESCUE_MAX_TEXT."""
    if _pdfplumber is None:
        return "", ""
    try:
        with _pdfplumber.open(_io.BytesIO(body)) as pdf:
            title = ""
            try:
                md = pdf.metadata or {}
                if md.get("Title"):
                    title = str(md["Title"])[:300]
            except Exception:
                pass
            parts: list[str] = []
            total = 0
            for page in pdf.pages[:80]:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                take = t[:_RESCUE_MAX_TEXT - total]
                parts.append(take)
                total += len(take)
                if total >= _RESCUE_MAX_TEXT:
                    break
            return title, "\n\n".join(p for p in parts if p).strip()
    except Exception:
        return "", ""


def _extract_pdf_pypdf(body: bytes) -> tuple[str, str, str]:
    """(title, text, error_code) via pypdf. error_code "" on success."""
    if _PdfReader is None:
        return "", "", "pypdf_missing"
    try:
        reader = _PdfReader(_io.BytesIO(body))
        title = ""
        try:
            if reader.metadata and reader.metadata.title:
                title = str(reader.metadata.title)[:300]
        except Exception:
            pass
        pages: list[str] = []
        total = 0
        for page in reader.pages[:80]:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            take = t[:_RESCUE_MAX_TEXT - total]
            pages.append(take)
            total += len(take)
            if total >= _RESCUE_MAX_TEXT:
                break
        return title, "\n\n".join(p for p in pages if p).strip(), ""
    except Exception as e:
        return "", "", f"pdf_error:{type(e).__name__}"


def _extract_pdf(body: bytes, url: str) -> tuple[str, str, float, str]:
    """Returns (title, text, quality, error_code). error_code is "" on success.
    Caps at 80 pages to keep token budget sane; reports pdf_no_text_layer for
    scanned PDFs (so the caller knows rendering will not help either).

    M3: tries pdfplumber first (better multi-column / table handling), then
    falls back to pypdf. Bounded: bodies above _PDF_MAX_BYTES never reach a
    parser (decompression bombs bound their input, not their page count), and
    the extracted text is capped at _RESCUE_MAX_TEXT."""
    if len(body) > _PDF_MAX_BYTES:
        return "", "", 0.0, "pdf_too_large"
    _load_pdf_extractors()
    if _pdfplumber is None and _PdfReader is None:
        return "", "", 0.0, "pdf_no_extractor"

    # 1) pdfplumber (preferred). Only adopt when it yields text.
    p_title, p_text = _extract_pdf_pdfplumber(body)
    if p_text:
        return p_title, p_text, _quality_score(p_text), ""

    # 2) pypdf fallback.
    y_title, y_text, y_err = _extract_pdf_pypdf(body)
    if y_text:
        return y_title, y_text, _quality_score(y_text), ""
    if y_err and y_err != "pypdf_missing":
        return y_title, "", 0.0, y_err

    # Neither produced text: prefer any title we found; report no text layer.
    return (p_title or y_title), "", 0.0, "pdf_no_text_layer"


def _looks_like_pdf(resp, final_url: str) -> bool:
    """Detect PDF by magic bytes OR explicit content-type OR .pdf URL.
    Covers the case where a server serves a PDF with text/html content-type."""
    body = getattr(resp, "content", None)
    if isinstance(body, (bytes, bytearray)) and len(body) >= 5 and bytes(body[:5]) == b"%PDF-":
        return True
    try:
        ctype = (dict(getattr(resp, "headers", {}) or {}).get("content-type", "") or "").lower()
    except Exception:
        ctype = ""
    if "pdf" in ctype:
        return True
    return final_url.lower().split("?")[0].endswith(".pdf")


def _main_content_text(html: str) -> str:
    """Extract the main article body via optional resiliparse, dropping
    boilerplate (nav/footer/sidebar/ads). Returns formatted plain text
    (lists/links/<pre> preserved), or "" when resiliparse is absent, the
    extraction fails, or the result is too thin to be real content — in which
    case the caller keeps the raw HTML."""
    if _extract_plain_text is None or not html:
        return ""
    try:
        txt = _extract_plain_text(
            html, main_content=True, preserve_formatting=True,
            list_bullets=True, links=False, alt_texts=False)
    except Exception:
        return ""
    txt = (txt or "").strip()
    return txt if len(txt) >= _MAINCONTENT_MIN_CHARS else ""


def _html_to_markdown(html: str) -> str:
    """Convert HTML to structure-preserving markdown via the optional
    markdownify lib. Returns "" when markdownify is absent or conversion fails
    or yields nothing usable — the caller then keeps the raw HTML.

    Script/style/head/noscript blocks are stripped first (markdownify would
    otherwise emit their inline text as junk). Tables → pipe tables and
    <pre>/<code> → fenced blocks are markdownify defaults."""
    if _markdownify is None or not html:
        return ""
    stripped = _re.sub(
        r"(?is)<(script|style|noscript|head|template|svg)[^>]*>.*?</\1>", " ", html)
    try:
        md = _markdownify.markdownify(
            stripped, heading_style="ATX", strip=["script", "style"])
    except Exception:
        return ""
    md = _re.sub(r"\n{3,}", "\n\n", (md or "")).strip()
    return md


def _extract_response(resp, final_url: str,
                      enable_markdown: bool = True,
                      enable_maincontent: bool = False) -> tuple[str, str, float, dict]:
    """HTTP 응답에서 제목, 본문, 품질과 추출 메타데이터를 반환해요."""
    if _looks_like_pdf(resp, final_url):
        body = getattr(resp, "content", None)
        if isinstance(body, (bytes, bytearray)) and body:
            # Re-guard: a .pdf URL can serve plain HTML — only hand pypdf a
            # body that really is a PDF (magic bytes or explicit content-type).
            ctype_pdf = False
            try:
                ctype_pdf = "pdf" in (dict(getattr(resp, "headers", {}) or {})
                                      .get("content-type", "") or "").lower()
            except Exception:
                pass
            if bytes(body[:5]) == b"%PDF-" or ctype_pdf:
                title, text, quality, err = _extract_pdf(bytes(body), final_url)
                if text:
                    return title, text, quality, {"source": "pdf", "error": err or ""}
                return title, f"[PDF binary, {len(body)} bytes; extractor={err or 'ok'}]", \
                       0.0, {"source": "pdf", "error": err}

    text = getattr(resp, "text", "") or ""
    if not text:
        body = getattr(resp, "content", None)
        if isinstance(body, (bytes, bytearray)) and body:
            return "", f"[{len(body)} bytes; binary]", 0.0, \
                   {"source": "raw_binary", "error": "no_text_body"}
        return "", "", 0.0, {"source": "empty", "error": "empty_body"}

    # Rescue parsers only ever scan a bounded prefix of the body; `content`
    # itself keeps the full raw text (that surface predates this chain).
    scan = text if len(text) <= _SCAN_LIMIT else text[:_SCAN_LIMIT]

    title = ""
    m = _re.search(r"<title[^>]*>(.*?)</title>", scan, _re.I | _re.S)
    if m:
        title = _re.sub(r"\s+", " ", m.group(1)).strip()[:300]

    visible = _visible_text(scan)
    content, source, quality = text, "raw", _quality_score(visible)

    jsonld = _extract_json_ld_text(scan)
    if len(jsonld) > _JSONLD_MIN_CHARS and len(jsonld) > len(visible):
        content, source, quality = jsonld, "json_ld", _quality_score(jsonld)

    # 원본 HTML일 때만 본문 추출을 적용해요.
    if enable_maincontent and source == "raw":
        main = _main_content_text(content)
        if main:
            return title, main, _quality_score(main), {
                "source": "maincontent", "error": ""}

    # 원본 HTML일 때만 마크다운으로 변환해요.
    if enable_markdown and source == "raw":
        md = _html_to_markdown(content)
        if md:
            content, quality = md, _quality_score(md)
            source = "raw+md"
    return title, content, quality, {"source": source, "error": ""}


def _maybe_extract(resp, final_url: str, *, enable_extraction: bool,
                   enable_markdown: bool = True,
                   enable_maincontent: bool = False) -> tuple[str, str, float, dict]:
    """Run rescue extraction when enabled; otherwise raw text + consistent meta."""
    if not enable_extraction:
        return "", getattr(resp, "text", "") or "", 0.0, \
               {"source": "raw_disabled", "error": ""}
    return _extract_response(resp, final_url,
                             enable_markdown=enable_markdown, enable_maincontent=enable_maincontent)


# --- curl_cffi probe executor ------------------------------------------------
def _curl_probe(
    url: str, *, impersonate: str, referer: str, timeout: int = 20,
    enable_retry: bool = False,
) -> tuple[Any, Optional[str]]:
    """Returns (response, error_str). response may be None on exception.

    Routes through the per-host SessionPool so cookies (WAF sensors) and the
    warm connection persist across attempts and across pages of the same host.
    The pool degrades to a one-shot GET when a Session can't be created.
    """
    from .transport import POOL
    return POOL.request(url, impersonate=impersonate, referer=referer, timeout=timeout,
                        max_retries=2 if enable_retry else 0)


def _run_attempt(
    url: str,
    *,
    transform_name: str,
    impersonate: str,
    referer_name: str,
    success_selectors: Optional[list[str]],
    known_bad_sizes: Optional[list[int]],
    timeout: int,
    phase: str,
    enable_retry: bool = False,
) -> tuple[Attempt, Any]:
    """Execute one curl_cffi attempt and produce an Attempt record."""
    referer_url = REFERER_STRATEGIES.get(referer_name, REFERER_STRATEGIES["none"])(url)
    t0 = time.time()
    resp, err = _curl_probe(url, impersonate=impersonate, referer=referer_url, timeout=timeout,
                            enable_retry=enable_retry)
    elapsed = round(time.time() - t0, 3)

    att = Attempt(
        phase=phase,
        executor="curl_cffi",
        url=url,
        url_transform=transform_name,
        impersonate=impersonate,
        referer=referer_name,
        elapsed_s=elapsed,
    )

    if err or resp is None:
        att.error = err or "no response"
        att.verdict = Verdict.UNKNOWN.value
        return att, None

    vr = validate(resp, success_selectors=success_selectors, known_bad_sizes=known_bad_sizes)
    att.status = vr.status
    att.body_size = vr.body_size
    att.verdict = vr.verdict.value
    att.reasons = vr.reasons
    if att.verdict in _OK_VALUES and (
        not 200 <= att.status < 300
        or not ((getattr(resp, "content", b"") or b"").strip() or (getattr(resp, "text", "") or "").strip())
    ):
        att.verdict = Verdict.UNKNOWN.value
        att.reasons = ["HTTP 성공 상태와 비어 있지 않은 본문이 필요해요."]
    return att, resp


# --- Diversity planner -------------------------------------------------------
@dataclass(frozen=True)
class _Cand:
    profile_id: str
    transform: str
    url: str
    impersonate: str
    referer: str
    known_bad_sizes: Optional[tuple]


_FAMILIES = ("safari_ios", "safari", "chrome_android", "chrome", "edge", "firefox")


def _family(tls: str) -> str:
    for fam in _FAMILIES:
        if tls.startswith(fam):
            return fam
    return tls


def _is_mobile_tls(t: str) -> bool:
    return ("ios" in t) or ("android" in t)


def _plan_for_profile(
    url: str, profile_id: str, profile: dict, device_class: str
) -> list[_Cand]:
    from .transport import filter_available
    groups: list[list[str]] = [filter_available(list(g)) for g in (profile.get("tls_impersonate_candidates") or [["safari", "chrome"]])]
    avoid = set(profile.get("tls_impersonate_avoid") or [])
    referer_order = list(profile.get("referer_strategies") or ["self_root"])
    transform_order = list(profile.get("url_transform_order") or ["original"])
    kb = profile.get("known_bad_sizes") or None
    known_bad = tuple(kb) if kb else None

    # device_class shaping (fixes desktop/mobile drift)
    if device_class == "mobile":
        groups = [[t for t in g if _is_mobile_tls(t)] for g in groups]
        for extra in ("mobile_subdomain", "am_prefix", "m_prefix_subdomain"):
            if extra not in transform_order:
                transform_order.append(extra)
    elif device_class == "desktop":
        groups = [[t for t in g if not _is_mobile_tls(t)] for g in groups]
        transform_order = [t for t in transform_order if t not in ("mobile_subdomain", "am_prefix", "m_prefix_subdomain")] or ["original"]

    # deprioritize (not delete) avoid targets within each family group
    def _reorder(g: list[str]) -> list[str]:
        return [t for t in g if t not in avoid] + [t for t in g if t in avoid]

    groups = [_reorder(g) for g in groups if g]
    if not groups:
        groups = [["safari", "chrome"]]

    transforms = iter_transformed(url, transform_order) or [("original", url)]

    # Diversity ordering: vary FAMILY fastest, then TRANSFORM, then version
    # DEPTH, then REFERER. A small budget thus touches every family/transform
    # before exhausting one family's old versions.
    max_depth = max(len(g) for g in groups)
    cands: list[_Cand] = []
    seen: set[tuple] = set()
    for ref in referer_order:
        for depth in range(max_depth):
            for (t_name, t_url) in transforms:
                for g in groups:
                    if depth >= len(g):
                        continue
                    imp = g[depth]
                    key = (t_url, imp, ref)
                    if key in seen:
                        continue
                    seen.add(key)
                    cands.append(_Cand(profile_id, t_name, t_url, imp, ref, known_bad))
    return cands


def _build_plan(
    url: str,
    hits: list,
    profiles: dict,
    device_class: str,
    probe_impersonate: str,
    probe_referer: str,
    priority: Optional[dict] = None,
) -> list[_Cand]:
    """Materialize a diversity-ordered candidate plan across the top profiles.

    Profiles are round-robin interleaved so a confident #1 profile cannot
    starve #2/#3. The probe combo is removed (already executed).

    `priority` (U5 self-learning): a previously-successful route
    ``{"transform","impersonate","referer"}`` for this host — the matching
    candidate is moved to the FRONT so a known-good route is retried first."""
    per: list[list[_Cand]] = []
    for hit in hits[:3]:
        pid = getattr(hit, "profile_id", None) or "unknown_challenge"
        prof = load_profile(pid, profiles=profiles)
        per.append(_plan_for_profile(url, pid, prof, device_class))

    probe_key = (url, probe_impersonate, probe_referer)
    merged: list[_Cand] = []
    seen: set[tuple] = set()
    i = 0
    while any(i < len(p) for p in per):
        for p in per:
            if i < len(p):
                c = p[i]
                key = (c.url, c.impersonate, c.referer)
                if key == probe_key or key in seen:
                    continue
                seen.add(key)
                merged.append(c)
        i += 1

    if priority:
        front = [c for c in merged if c.transform == priority.get("transform")
                 and c.impersonate == priority.get("impersonate")
                 and c.referer == priority.get("referer")]
        if front:
            rest = [c for c in merged if c not in front]
            merged = front + rest
    return merged


# --- Public entrypoint: self-learning wrapper (U5) ---------------------------
def _winning_route(result: FetchResult) -> Optional[dict]:
    """Extract the curl route that produced the OK result, from the trace.

    Only probe/grid curl wins are learnable: Phase 0 always runs first anyway,
    and a browser win carries no reusable curl identity."""
    for att in reversed(result.trace):
        if (att.verdict in _OK_VALUES and att.phase in ("probe", "grid")
                and att.executor == "curl_cffi" and att.impersonate):
            return {
                "transform": att.url_transform,
                "impersonate": att.impersonate,
                "referer": att.referer,
                "phase": att.phase,
            }
    return None


def fetch(
    url: str,
    *,
    success_selectors: Optional[list[str]] = None,
    device_class: str = "auto",
    user_hint: Optional[dict] = None,
    timeout: int = 25,
    max_attempts: Optional[int] = None,
    max_browser_attempts: int = 2,
    enable_playwright: bool = True,
    enable_phase0: bool = True,
    enable_learning: bool = True,
    enable_extraction: bool = True,
    enable_retry: bool = True,
    enable_markdown: bool = True,
    enable_maincontent: bool = False,
) -> FetchResult:
    """Public entrypoint — the generic grid wrapped with per-host self-learning.

    1. Before fetching, look up the route that last succeeded for this host and
       promote it: it becomes the probe identity AND the front of the grid.
    2. After fetching, record the winning route; or, if a learned route was
       promoted and the run hit a REAL block, strike it (evicted after two
       consecutive strikes — see `learning.py`).

    The store is a bounded, self-pruning JSON file; any error in it is swallowed
    so learning can never break a fetch. Disable per-call with
    ``enable_learning=False`` or globally with ``INSANE_LEARN=0``.

    ``enable_playwright``와 ``max_browser_attempts``는 호환 인자로만 받아요.
    값과 관계없이 HTTP만 실행하며 외부 브라우저는 모델이 호출해요.
    PDF와 JSON-LD 본문 추출은 ``enable_extraction``으로 제어해요.

    ``enable_retry`` (default True) retries transient statuses (429/502/503/
    504) on the PROBE attempt with exponential backoff, honouring a numeric
    ``Retry-After``. Grid attempts never retry — a failing grid must not
    multiply sleeps across dozens of candidates.

    ``enable_markdown`` (default True) converts a raw-HTML success to
    structure-preserving markdown via markdownify (tables → pipe tables,
    <pre>/<code> → fences); ``extraction_source`` becomes "raw+md". Set False
    for raw HTML. No-op when markdownify is not installed.
    ``enable_maincontent`` (opt-in) instead strips boilerplate via resiliparse."""
    priority: Optional[dict] = None
    learned_existed = False
    uh = dict(user_hint or {})
    try:
        from . import learning
        if enable_learning and learning.enabled():
            priority = learning.lookup(url, device_class)
            if priority:
                learned_existed = True
                uh.setdefault("impersonate_first", priority.get("impersonate"))
                uh.setdefault("referer_strategy", priority.get("referer"))
    except Exception:
        priority = None

    result = _fetch_core(
        url, success_selectors=success_selectors, device_class=device_class,
        user_hint=uh, timeout=timeout, max_attempts=max_attempts,
        max_browser_attempts=max_browser_attempts,
        enable_playwright=enable_playwright, enable_phase0=enable_phase0,
        priority=priority,
        enable_extraction=enable_extraction, enable_retry=enable_retry,
        enable_markdown=enable_markdown, enable_maincontent=enable_maincontent,
    )

    try:
        from . import learning
        if enable_learning and learning.enabled():
            if result.ok:
                win = _winning_route(result)
                if win:
                    learning.record_success(url, device_class, win)
            elif learned_existed:
                learning.record_failure(
                    url, device_class,
                    penalize=learning.is_real_failure(result.verdict))
    except Exception:
        pass

    try:
        from .observations_log import log_fetch
        log_fetch(url, result)
    except Exception:
        pass

    return result


# --- Main entrypoint ---------------------------------------------------------
def _fetch_core(
    url: str,
    *,
    success_selectors: Optional[list[str]] = None,
    device_class: str = "auto",      # "auto" | "desktop" | "mobile"
    user_hint: Optional[dict] = None,
    timeout: int = 25,
    max_attempts: Optional[int] = None,   # None = exhaustive (R6); int = budget
    max_browser_attempts: int = 2,
    enable_playwright: bool = True,
    enable_phase0: bool = True,
    priority: Optional[dict] = None,      # U5: learned route to retry first
    enable_extraction: bool = True,
    enable_retry: bool = True,
    enable_markdown: bool = True,
    enable_maincontent: bool = False,
) -> FetchResult:
    """Fetch `url` using the generic diversity grid.

    max_attempts
        None (default) → run the whole plan (exhaustive, honours R6).
        int → TOTAL curl-attempt budget (probe included). On budget exit the
        result reports `stop_reason="budget"`, `grid_exhausted=False`, so
        callers never mistake a truncated run for a true exhaustive failure.
    """
    user_hint = user_hint or {}
    profiles = _load_profiles()
    trace: list[Attempt] = []
    last_resp = None
    last_attempt: Optional[Attempt] = None
    best_suspect: Optional[tuple] = None   # (resp, attempt)
    profile_used: Optional[str] = None

    _jmin = int(os.environ.get("INSANE_JITTER_MS_MIN", "150"))
    _jmax = int(os.environ.get("INSANE_JITTER_MS_MAX", "400"))

    def _jitter():
        time.sleep(random.uniform(_jmin / 1000.0, _jmax / 1000.0))

    # Surface profile-loader failures as a diagnostic trace entry (not counted
    # as a network attempt).
    load_err = last_load_error()
    if load_err:
        trace.append(Attempt(
            phase="probe", executor="profile_loader", url=url,
            url_transform="original", impersonate=None, referer="",
            verdict=Verdict.UNKNOWN.value, error=f"profiles_fallback: {load_err}",
        ))

    # -------- Phase 0: official public-API router (R5; site-aware, sanctioned) --
    # For recognised platforms (Reddit/X/YouTube/...) try the official no-auth
    # endpoint BEFORE the generic grid. This is the *enforced* version of the
    # old agent-driven SKILL snippets — the agent can no longer skip it, which
    # is what made Reddit/X look "blocked" (grid 403'd .json; nobody tried .rss).
    if enable_phase0:
        try:
            from .phase0 import route as _phase0_route
            p0 = _phase0_route(url, timeout=timeout)
        except Exception as e:  # router must never break the generic chain
            p0 = None
            trace.append(Attempt(
                phase="phase0", executor="phase0", url=url, url_transform="original",
                impersonate=None, referer="", verdict=Verdict.UNKNOWN.value,
                error=f"{type(e).__name__}:{str(e)[:120]}",
            ))
        if p0 is not None:
            for a in p0["attempts"]:
                trace.append(Attempt(
                    phase="phase0", executor=a["route"], url=url, url_transform="-",
                    impersonate=None, referer="",
                    status=a.get("status", 0), body_size=a.get("bytes", 0),
                    verdict=(Verdict.STRONG_OK.value if a["ok"] else Verdict.BLOCKED.value),
                    reasons=[a["note"]] if a.get("note") else [],
                ))
            if p0["ok"] and p0.get("content", "").strip() and any(
                a.get("ok") and 200 <= a.get("status", 0) < 300
                for a in p0["attempts"]
            ):
                trunc = {k: p0[k] for k in ("truncated_possible", "truncation_reason") if k in p0}
                return FetchResult(
                    ok=True, content=p0["content"], final_url=p0["final_url"],
                    verdict=Verdict.STRONG_OK.value,
                    profile_used=f"phase0:{p0['platform']}", trace=trace,
                    summary=f"Phase 0 공식 경로 {p0['platform']}:{p0['route']}에서 수집했어요."
                            + (f" 일부 내용이 생략될 수 있어요: {trunc.get('truncation_reason')}." if trunc else ""),
                    stop_reason="HTTP 수집에 성공했어요.",
                    extraction_meta=trunc,
                )
            # Recognised platform but every official route failed → fall through
            # to the generic grid (don't give up; R6).

    # -------- Phase 1: probe -------------------------------------------------
    base_impersonate = user_hint.get("impersonate_first") or (
        "safari_ios" if device_class == "mobile" else "safari")
    from .transport import available_impersonates
    _avail = available_impersonates()
    if _avail is not None and base_impersonate not in _avail:
        base_impersonate = "chrome"
    base_referer = user_hint.get("referer_strategy") or "self_root"

    # Root warmup (deep URLs only): let a WAF sensor set a resolved cookie on
    # the probe identity's session before the deep request — the classic
    # first-hit rejection fix. Skipped when the target already IS the root.
    try:
        from .transport import POOL, pool_enabled, _host_of, _root_of
        if pool_enabled():
            _root = _root_of(url)
            if _root != url:
                POOL.warmup(_host_of(url), base_impersonate, _root, timeout=min(timeout, 15))
    except Exception:
        pass

    curl_attempts = 0
    # Transient-status retry fires on the PROBE only: retrying each of the
    # dozens of grid candidates as well would multiply backoff sleeps into a
    # tens-of-seconds failure path.
    probe_attempt, probe_resp = _run_attempt(
        url, transform_name="original", impersonate=base_impersonate,
        referer_name=base_referer, success_selectors=success_selectors,
        known_bad_sizes=None, timeout=timeout, phase="probe",
        enable_retry=enable_retry,
    )
    trace.append(probe_attempt)
    curl_attempts += 1
    if probe_resp is not None:
        last_resp, last_attempt = probe_resp, probe_attempt
        if probe_attempt.verdict in _OK_VALUES:
            return _build_result(probe_resp, probe_attempt, trace, profile_used=None,
                                 planned=0, executed=curl_attempts,
                                 grid_exhausted=False, stop_reason="success",
                                 enable_extraction=enable_extraction,
                                 enable_markdown=enable_markdown, enable_maincontent=enable_maincontent)
        if probe_attempt.verdict == Verdict.SUSPECT_OK.value:
            best_suspect = (probe_resp, probe_attempt)
        elif probe_attempt.verdict in _TERMINAL_NONSUCCESS_VALUES:
            return _give_up(trace, profile_used, last_resp, last_attempt, best_suspect,
                            planned=0, executed=curl_attempts, grid_exhausted=False,
                            stop_reason=probe_attempt.verdict)

    # -------- Phase 2: detect + plan + execute ------------------------------
    if last_resp is not None:
        hits = detect(last_resp, profiles=profiles)
    else:
        hits = [type("H", (), {"profile_id": "unknown_challenge", "confidence": 0.1,
                               "signals": ["no_probe_response"]})()]
    profile_used = hits[0].profile_id if hits else None

    plan = _build_plan(url, hits, profiles, device_class, base_impersonate,
                       base_referer, priority=priority)
    planned = len(plan)
    grid_exhausted = False
    stop_reason = ""

    for cand in plan:
        if max_attempts is not None and curl_attempts >= max_attempts:
            stop_reason = "budget"
            break
        att, resp = _run_attempt(
            cand.url, transform_name=cand.transform, impersonate=cand.impersonate,
            referer_name=cand.referer, success_selectors=success_selectors,
            known_bad_sizes=list(cand.known_bad_sizes) if cand.known_bad_sizes else None,
            timeout=timeout, phase="grid",
        )
        trace.append(att)
        curl_attempts += 1
        if resp is not None:
            last_resp, last_attempt = resp, att
            if att.verdict in _OK_VALUES:
                return _build_result(resp, att, trace, profile_used=cand.profile_id,
                                     planned=planned, executed=curl_attempts,
                                     grid_exhausted=False, stop_reason="success",
                                     enable_extraction=enable_extraction,
                                     enable_markdown=enable_markdown, enable_maincontent=enable_maincontent)
            if att.verdict == Verdict.SUSPECT_OK.value and best_suspect is None:
                best_suspect = (resp, att)
            if att.verdict in _TERMINAL_NONSUCCESS_VALUES:
                stop_reason = att.verdict
                break
        # continuing → polite jitter (only on non-terminal failure)
        _jitter()
    else:
        grid_exhausted = True
        stop_reason = "exhausted"

    # Phase 3에서는 로컬 실행 없이 모델의 외부 browser_use 호출로 넘겨요.
    # -------- Give up, return best we have ----------------------------------
    return _give_up(trace, profile_used, last_resp, last_attempt, best_suspect,
                    planned=planned, executed=curl_attempts,
                    grid_exhausted=grid_exhausted, stop_reason=stop_reason or "exhausted")


def _untried_routes(stop_reason, grid_exhausted) -> tuple[list[str], bool]:
    """인증이나 없는 문서가 아니면 모델의 외부 브라우저 호출을 안내해요."""
    if stop_reason in _BROWSER_FUTILE_VALUES:
        return [], False
    return ["browser_use"], True


_REAL_EXECUTORS = frozenset({"curl_cffi"})
_INFRA_AUTH_VERDICTS = frozenset({Verdict.AUTH_REQUIRED.value, Verdict.NOT_FOUND.value})
_WAF_VERDICTS = frozenset({
    Verdict.CHALLENGE.value, Verdict.BLOCKED.value,
    Verdict.RATE_LIMITED.value, Verdict.SUSPECT_OK.value})


def _classify_block(trace) -> str:
    """Differential block classification (Bamberg §5.3): compare the outcomes
    of the routes actually tried.

    Returns "bot_detection" (routes disagree, or any WAF/challenge signal →
    trying a browser / other routes may help), "infra_or_auth" (every real
    route uniformly 401/404 → a wall stealth cannot clear), or "" when there is
    not enough signal to say. Only meaningful on the failure path."""
    real = [a for a in trace
            if a.executor in _REAL_EXECUTORS
            and a.verdict and a.verdict != Verdict.UNKNOWN.value]
    if not real:
        return ""
    verdicts = {a.verdict for a in real}
    statuses = {a.status for a in real if a.status}

    # Every real route is a hard 401/404 wall → stealth won't help.
    if verdicts <= _INFRA_AUTH_VERDICTS:
        return "infra_or_auth"
    # Routes disagree (distinct verdicts or distinct statuses), or a WAF /
    # challenge signal is present → bot detection, which escalation may beat.
    if len(verdicts) > 1 or len(statuses) > 1 or (verdicts & _WAF_VERDICTS):
        return "bot_detection"
    return ""


def _give_up(trace, profile_used, last_resp, last_attempt, best_suspect,
             *, planned, executed, grid_exhausted, stop_reason) -> FetchResult:
    """Return the most honest failure result, preferring suspect content."""
    untried, needs_browser = _untried_routes(stop_reason, grid_exhausted)
    stop_reason = (
        "인증이 필요해서 수집을 중단했어요." if stop_reason == Verdict.AUTH_REQUIRED.value else
        "문서를 찾을 수 없어서 수집을 중단했어요." if stop_reason == Verdict.NOT_FOUND.value else
        "HTTP 수집을 마치고 browser_use 호출이 필요해요."
    )
    block_class = _classify_block(trace)
    if best_suspect is not None and needs_browser:
        s_resp, s_att = best_suspect
        content = getattr(s_resp, "text", "") if s_resp is not None else ""
        return FetchResult(
            ok=False, content=content or "",
            final_url=str(getattr(s_resp, "url", s_att.url)) if s_resp is not None else s_att.url,
            verdict=s_att.verdict, profile_used=profile_used, trace=trace,
            summary=_format_summary(trace, profile_used, stop_reason),
            planned_attempts=planned, executed_attempts=executed,
            grid_exhausted=grid_exhausted, stop_reason=stop_reason,
            untried_routes=untried, needs_browser=needs_browser,
            block_class=block_class,
        )
    return FetchResult(
        ok=False,
        content=getattr(last_resp, "text", "") if last_resp is not None else "",
        final_url=str(getattr(last_resp, "url", url_of(last_attempt))) if last_resp is not None else url_of(last_attempt),
        verdict=last_attempt.verdict if last_attempt else Verdict.UNKNOWN.value,
        profile_used=profile_used, trace=trace,
        summary=_format_summary(trace, profile_used, stop_reason),
        planned_attempts=planned, executed_attempts=executed,
        grid_exhausted=grid_exhausted, stop_reason=stop_reason,
        untried_routes=untried, needs_browser=needs_browser,
        block_class=block_class,
    )


def url_of(attempt: Optional[Attempt]) -> str:
    return attempt.url if attempt else ""


def fetch_many(urls: list[str], **kwargs) -> list[FetchResult]:
    """호스트별 HTTP 세션을 재사용해서 여러 URL을 수집해요."""
    by_host: dict[str, list[int]] = {}
    for i, u in enumerate(urls):
        from .transport import _host_of
        by_host.setdefault(_host_of(u), []).append(i)
    results: list[Optional[FetchResult]] = [None] * len(urls)
    for _host, idxs in by_host.items():
        for i in idxs:
            results[i] = fetch(urls[i], **kwargs)
    return [r for r in results if r is not None]


def _build_result(resp, attempt: Attempt, trace: list[Attempt], profile_used: Optional[str],
                  *, planned: int, executed: int, grid_exhausted: bool, stop_reason: str,
                  enable_extraction: bool = True, enable_markdown: bool = True,
                  enable_maincontent: bool = False) -> FetchResult:
    final_url = str(getattr(resp, "url", attempt.url))
    _t, content, quality, meta = _maybe_extract(
        resp, final_url, enable_extraction=enable_extraction,
        enable_markdown=enable_markdown, enable_maincontent=enable_maincontent)
    return FetchResult(
        ok=True,
        content=content,
        final_url=final_url,
        verdict=attempt.verdict,
        profile_used=profile_used,
        trace=trace,
        summary=f"HTTP 경로 {attempt.executor}에서 수집에 성공했어요.",
        planned_attempts=planned, executed_attempts=executed,
        grid_exhausted=grid_exhausted, stop_reason="HTTP 수집에 성공했어요.",
        extraction_quality=quality,
        extraction_source=meta.get("source", ""),
        extraction_meta=meta,
    )


def _format_summary(trace: list[Attempt], profile: Optional[str], stop_reason: str = "") -> str:
    return (
        f"HTTP 요청 {len(trace)}회 후 수집하지 못했어요. {stop_reason} "
        "필요한 경우 모델이 sleepysoong:browser_use를 호출해 공개 내용을 확인해요. "
        "인증, CAPTCHA, 보안 검사와 접근 차단을 우회하지 않아요."
        if stop_reason == "HTTP 수집을 마치고 browser_use 호출이 필요해요."
        else f"HTTP 요청 {len(trace)}회 후 수집하지 못했어요. {stop_reason}"
    )
