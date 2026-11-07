English | [한국어](README.ko.md) | [中文](README.zh.md) | [日本語](README.ja.md) | [Español](README.es.md)

<div align="center">

# insane-search

**Impossible is nothing. If it's public, insane-search gets in.**

A resilient public-page reader for Claude Code. No API keys, no proxy setup.

<p>
  <a href="https://docs.anthropic.com/en/docs/claude-code"><img src="https://img.shields.io/badge/platform-Claude_Code-D97757?logo=claude" alt="Claude Code"></a>
  <img src="https://img.shields.io/badge/API_key-not_required-3FB950" alt="No API key">
  <a href="https://github.com/fivetaku/gptaku_plugins"><img src="https://img.shields.io/badge/part_of-gptaku--plugins-6E56CF" alt="part of gptaku-plugins"></a>
  <a href="https://github.com/fivetaku/insane-search/stargazers"><img src="https://img.shields.io/github/stars/fivetaku/insane-search?style=flat&color=F0B72F" alt="stars"></a>
</p>

<!-- Hero — cinematic key-art: a blocked site (403 / CAPTCHA / WAF) shatters as
     insane-search breaks through and returns real public content with its source. -->
<img src="assets/hero.png" width="860" alt="Cinematic split: on the left a blocked site shows 403 Forbidden, a CAPTCHA, and a WAF wall; it shatters down the middle as insane-search breaks through on the right, returning a real public post from @claudeai (Claude Code Plugins) with its source — no API key.">

</div>

---

## New in v0.16.3

- **One fetch for content and trace:** `--json-content` returns metadata, trace, and wrapped untrusted text together, without fetching the same URL again for diagnostics. Existing `--json` output still omits the body.
- **Lazy PDF parsers:** `pdfplumber` and `pypdf` load only when PDF extraction is needed, not during ordinary HTML startup. PDF extraction and fallback behavior are preserved.

## ⚡ Install

```bash
/plugin marketplace add https://github.com/fivetaku/gptaku_plugins.git
/plugin install insane-search@gptaku-plugins
/reload-plugins
```

No commands to learn. Ask Claude Code normally — insane-search kicks in when a fetch gets blocked.

## 💬 Try it

Just ask normally — insane-search kicks in when a fetch gets blocked:

> *"Find what people are saying about Claude Code on Reddit and summarize the top threads."*
> *"Search X for posts about insane-search."*
> *"Summarize this YouTube video."*

**Expected:** Claude reaches each site's public route — Reddit's feed, X through free Brave/Yahoo discovery plus tweet-result validation, YouTube captions — with no login and no API key. If xAI credentials are already available, X keyword discovery is automatically augmented with native `x_search`; the free route remains active and can be forced with `INSANE_SEARCH_XAI=off`.

## 🌐 Works on

**X · Reddit · YouTube · Hacker News · Naver · Coupang · LinkedIn · Medium · Substack · arXiv · GitHub · Stack Overflow · Bluesky · Mastodon** — plus any site with a public page, feed, or `/rss`. Full platform list & methods → [PLATFORMS.md](PLATFORMS.md).

## ⚙️ Why it gets through

- **HTTP 수집과 브라우저를 분리해요** — 공개 API·피드와 HTTP Phase 0~3 경로를 먼저 사용해요.
- **로컬 브라우저는 실행하지 않아요** — 옵션 생략과 `enable_playwright=True`도 HTTP-only예요. `--no-playwright`는 호환 스위치예요.
- **모델이 공식 도구를 호출해요** — `needs_browser=true`, `untried_routes=["browser_use"]`이면 모델이 `sleepysoong:browser_use`의 `browser_use`로 공개 페이지를 확인해요.
- **Zero setup** — auto-installs what it needs (`curl_cffi`, `yt-dlp`, …) on first use. No API keys, no signup.

## 🆚 Default Claude Code vs `+ insane-search`

| When you hit… | Claude Code alone | `+ insane-search` |
| :--- | :--- | :--- |
| 공개 페이지의 HTTP 403 | 수집에 실패할 수 있어요. | HTTP 진단을 반환하고 필요하면 모델이 공식 `browser_use`를 호출해요. |
| Platform content (X, Reddit, HN) | ✖ often blocked or empty | ✓ public API readers + syndication |
| CAPTCHA·보안 확인·접근 차단 | 중단해요. | 우회하지 않고 수집 한계를 알려요. |
| A media page (YouTube, 1,800+ sites) | ✖ no transcript | ✓ `yt-dlp` metadata + captions |
| Missing tools (`curl_cffi`, `yt-dlp`) | — | ✓ auto-installs on first use |
| API keys / signup | — | ✓ none |
| A **login wall or paywall** | ✖ | ✖ **stops here, and says so** (see Boundaries) |

HTTP 예외·빈 본문·오류 응답은 성공으로 바꾸지 않아요. 브라우저가 필요하면 모델이 공식 도구를 호출하며, 실제 결과만 근거로 사용해요.

## ✨ What just happened

| Without it | With insane-search |
| :--- | :--- |
| Ordinary fetch hits `403` and Claude says it can't read the page | The plugin picks a public-access route and returns usable text |
| You manually try mirrors, archives, mobile URLs | Fallbacks escalate automatically, public-only |
| A blocked page is a dead end | Metadata and structured data still yield titles, prices, summaries |

## 🔁 How it works

HTTP Phase 0~3 수집과 진단을 유지하고 외부 브라우저 호출은 모델에 인계해요. 엔진은 브라우저나 MCP 서버를 설치하지 않아요.

<details>
<summary><strong>Phase 0→3 adaptive scheduler — details</strong></summary>

Each phase runs only if the previous one fails or detects a blocking signal:

- **Phase 0** — special public endpoints (platform APIs, feeds) it can't discover generically
- **Phase 1** — lightweight probes: public API readers, syndication gateways, mobile / `.json` / `/rss` URL variants
- **Phase 2** — TLS impersonation (curl_cffi: safari → chrome → firefox) with a full browser identity
- **브라우저 인계** — HTTP 수집으로 본문을 얻지 못하고 `needs_browser=true`이면 모델이 공식 `browser_use`를 호출해요. HTTP 성공은 `needs_browser=false`예요.
- **Exit** — a login or paywall is detected: it reports *"authentication required"* rather than pretending

Every response is also scanned for OGP / JSON-LD, so even partial pages yield titles, summaries, and prices.
</details>

## 🔒 Boundaries

insane-search is a **reader for public content**, not a way around authentication.

- Reaches what's available through public pages, public APIs, feeds, archives, and a browser's public responses.
- **인증·CAPTCHA·보안 확인·접근 차단에서 멈춰요** — 브라우저에서도 우회하지 않아요.
- Never logs in as you and never stores or transmits credentials.
- All routes use no-auth public endpoints and standard, documented techniques.
- **You are responsible** for lawful, authorized use — each site's Terms of Service, `robots.txt`, rate limits, and applicable law. This is a dual-use developer tool; see [DISCLAIMER.md](DISCLAIMER.md).

## License

MIT — see [DISCLAIMER.md](DISCLAIMER.md) for acceptable-use and user-responsibility terms.

---

<div align="center">

**Part of [gptaku-plugins](https://github.com/fivetaku/gptaku_plugins)** — Claude Code plugins that break through the walls everything else stops at.

</div>
