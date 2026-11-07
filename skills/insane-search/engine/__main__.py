#!/usr/bin/env python3
"""CLI entrypoint for the insane-search engine.

Usage:
    python3 -m engine URL [--selector CSS] [--device auto|desktop|mobile]
                          [--timeout N] [--max-attempts N] [--json] [--trace]

Examples:
    python3 -m engine "https://example.com/" --selector "h1"
    python3 -m engine "https://example.com/" --json
    python3 -m engine "https://example.com/" --device mobile --trace

Exit codes:
    0   strong_ok or weak_ok
    1   ok=False (all attempts failed)
    2   CLI arg error
"""
from __future__ import annotations

import argparse
import json
import sys

from . import fetch
from .url_masking import mask_url

# Windows consoles default to a legacy codepage (e.g. cp949); without this the
# final print raises UnicodeEncodeError and discards an already-fetched page.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m engine",
                                description="Generic WAF-profile fetch chain.")
    p.add_argument("url", help="URL to fetch.")
    p.add_argument("--selector", "-s", action="append", default=None,
                   dest="selectors", metavar="CSS",
                   help="Positive-proof CSS selector. Repeatable.")
    p.add_argument("--device", choices=("auto", "desktop", "mobile"), default="auto",
                   help="Device class pin.")
    p.add_argument("--timeout", type=int, default=25,
                   help="Per-attempt timeout seconds (default 25).")
    p.add_argument("--max-attempts", type=int, default=None,
                   help="TOTAL curl-attempt budget. Default: None = exhaustive (honours R6).")
    p.add_argument("--no-retry", action="store_true",
                   help="Disable transient-status (429/502/503/504) probe retry.")
    p.add_argument("--no-extract", action="store_true",
                   help="PDF와 JSON-LD 본문 추출을 끄고 원본 응답을 반환해요.")
    p.add_argument("--no-markdown", action="store_true",
                   help="Disable markdownification. By default a raw-HTML success is "
                        "converted to structure-preserving markdown (tables/code kept) "
                        "via markdownify; this returns the raw HTML instead.")
    p.add_argument("--maincontent", action="store_true",
                   help="Strip boilerplate (nav/footer/ads) to the article body via "
                        "optional resiliparse. Off by default; wins over --markdown.")
    p.add_argument("--no-playwright", action="store_true",
                   help="HTTP-only 호환 옵션이에요. 생략해도 로컬 브라우저는 실행하지 않아요.")
    p.add_argument("--no-phase0", action="store_true",
                   help="Skip the Phase 0 official-API router (generic grid only).")
    p.add_argument("--json", action="store_true",
                   help="Emit FetchResult as JSON to stdout (content omitted).")
    p.add_argument("--json-content", action="store_true",
                   help="Emit metadata, trace and wrapped untrusted text from one fetch; URL fields are masked.")
    p.add_argument("--trace", action="store_true",
                   help="Print per-attempt trace to stderr.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = fetch(
            args.url,
            success_selectors=args.selectors,
            device_class=args.device,
            timeout=args.timeout,
            max_attempts=args.max_attempts,
            enable_playwright=not args.no_playwright,
            enable_phase0=not args.no_phase0,
            enable_extraction=not args.no_extract,
            enable_retry=not args.no_retry,
            enable_markdown=not args.no_markdown,
            enable_maincontent=args.maincontent,
        )
    except Exception as e:
        print(f"수집 엔진 오류가 발생했어요: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if args.trace:
        print("=== trace ===", file=sys.stderr)
        for att in result.trace:
            d = att.to_dict()
            imp = d.get("impersonate") or "-"
            ref = mask_url(d.get("referer") or "") or "-"
            print(
                f"[{d['phase']:<8}] {d['executor']:<18} "
                f"xform={d['url_transform']:<16} imp={imp:<14} ref={ref:<14} "
                f"status={d['status']:>4} size={d['body_size']:>8} "
                f"verdict={d['verdict']} {('err=' + d['error'][:60]) if d.get('error') else ''}",
                file=sys.stderr,
            )
        print(f"=== summary: {result.summary} ===", file=sys.stderr)

    if not result.ok and result.needs_browser:
        print(result.summary, file=sys.stderr)

    if args.json or args.json_content:
        payload = result.to_dict()
        if args.json_content:
            payload["final_url"] = mask_url(result.final_url)
            for attempt in payload["trace"]:
                attempt["url"] = mask_url(attempt["url"])
                attempt["referer"] = mask_url(attempt["referer"])
            payload["untrusted_text"] = result.to_untrusted_text()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(result.to_untrusted_text(), end="")
        if result.prompt_injection_risk in ("medium", "high"):
            signals = ",".join(result.prompt_injection_signals) or "none"
            print(
                f"[engine] prompt_injection_risk={result.prompt_injection_risk} signals={signals}",
                file=sys.stderr,
            )
        print(f"\n[engine] ok={result.ok} verdict={result.verdict} "
              f"profile={result.profile_used} attempts={len(result.trace)}",
              file=sys.stderr)

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
