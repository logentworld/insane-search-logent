[English](README.md) | [한국어](README.ko.md) | [中文](README.zh.md) | 日本語 | [Español](README.es.md)

<div align="center">

# insane-search

**Impossible is nothing. 公開ページなら、insane-search はいずれ突破する。**

Claude Code 向けの、ブロックに強い公開ページリーダー。API キーもプロキシ設定も不要。

<p>
  <a href="https://docs.anthropic.com/en/docs/claude-code"><img src="https://img.shields.io/badge/platform-Claude_Code-D97757?logo=claude" alt="Claude Code"></a>
  <img src="https://img.shields.io/badge/API_key-not_required-3FB950" alt="No API key">
  <a href="https://github.com/fivetaku/gptaku_plugins"><img src="https://img.shields.io/badge/part_of-gptaku--plugins-6E56CF" alt="part of gptaku-plugins"></a>
  <a href="https://github.com/fivetaku/insane-search/stargazers"><img src="https://img.shields.io/github/stars/fivetaku/insane-search?style=flat&color=F0B72F" alt="stars"></a>
</p>

<!-- Hero — cinematic key-art: a blocked site (403 / CAPTCHA / WAF) shatters as
     insane-search breaks through and returns real public content with its source. -->
<img src="assets/hero.png" width="860" alt="シネマティックな分割画面：左は 403 Forbidden・CAPTCHA・WAF でブロックされたサイト。中央から砕け、右で insane-search が突破し、API キーなしで @claudeai（Claude Code Plugins）の実際の公開ポストを出典付きで取得する。">

</div>

---

## v0.16.3 の変更点

- **1 回の取得で本文と trace を返す：** `--json-content` はメタデータ、trace、信頼できないコンテンツの境界マーカーで囲んだ本文をまとめて返します。診断のために同じ URL を再取得する必要はありません。従来の `--json` は本文を含まない形式を維持します。
- **PDF パーサーの遅延読み込み：** `pdfplumber` と `pypdf` は PDF 抽出が必要なときだけ読み込み、通常の HTML エンジン起動時には読み込みません。PDF 抽出とフォールバックの動作は維持します。

## ⚡ インストール

```bash
/plugin marketplace add https://github.com/fivetaku/gptaku_plugins.git
/plugin install insane-search@gptaku-plugins
/reload-plugins
```

覚えるコマンドはありません。いつも通り Claude Code に話しかければ、フェッチがブロックされた瞬間に insane-search が割り込みます。

## 💬 使ってみる

普通に頼むだけ——ブロックされた瞬間に insane-search が動きます：

> *"Reddit で Claude Code の反応を探して、人気スレッドを要約して。"*
> *"X で insane-search に関する投稿を検索して。"*
> *"この YouTube 動画を要約して。"*

**期待される動作：** Claude が各サイトの公開ルート——Reddit のフィード、X の無料 Brave・Yahoo 検索と tweet-result 検証、YouTube の字幕——にログインも API キーもなしで到達し、使えるテキストを返します。プラグインがなければ同じ依頼に *"アクセスできません"* が返るところを。xAI の認証情報がすでにあれば、X のキーワード検索にネイティブ `x_search` が自動で併用されます。無料ルートは常に残り、`INSANE_SEARCH_XAI=off` で無料ルートのみに固定できます。

## 🌐 対応サイト

**X · Reddit · YouTube · Hacker News · Naver · Coupang · LinkedIn · Medium · Substack · arXiv · GitHub · Stack Overflow · Bluesky · Mastodon** ——さらに公開ページ・フィード・`/rss` を持つあらゆるサイト。全プラットフォーム一覧と手法 → [PLATFORMS.md](PLATFORMS.md)。

## ⚙️ なぜ突破できるのか

- **HTTP 수집과 브라우저를 분리해요** — 공개 API·피드와 HTTP Phase 0~3 경로를 먼저 사용해요.
- **로컬 브라우저는 실행하지 않아요** — 옵션 생략과 `enable_playwright=True`도 HTTP-only예요. `--no-playwright`는 호환 스위치예요.
- **모델이 공식 도구를 호출해요** — `needs_browser=true`, `untried_routes=["browser_use"]`이면 모델이 `sleepysoong:browser_use`의 `browser_use`로 공개 페이지를 확인해요.
- **セットアップ不要** —— 必要なツール（`curl_cffi`、`yt-dlp` など）を初回利用時に自動インストール。API キーも登録も不要。

## 🆚 デフォルト Claude Code vs `+ insane-search`

| こんなとき… | Claude Code 単体 | `+ insane-search` |
| :--- | :--- | :--- |
| 공개 페이지의 HTTP 403 | 수집에 실패할 수 있어요. | HTTP 진단을 반환하고 필요하면 모델이 공식 `browser_use`를 호출해요. |
| プラットフォームのコンテンツ（X、Reddit、HN） | ✖ よくブロック・空応答 | ✓ 公開 API リーダー + シンジケーション |
| CAPTCHA·보안 확인·접근 차단 | 중단해요. | 우회하지 않고 수집 한계를 알려요. |
| メディアページ（YouTube など 1,800+ サイト） | ✖ 字幕なし | ✓ `yt-dlp` メタデータ + 字幕 |
| ツール未導入（`curl_cffi`、`yt-dlp`） | — | ✓ 初回利用時に自動インストール |
| API キー / 登録 | — | ✓ 不要 |
| **ログインウォール / ペイウォール** | ✖ | ✖ **ここで止まり、そう伝える**（Boundaries 参照） |

HTTP 예외·빈 본문·오류 응답은 성공으로 바꾸지 않아요. 브라우저가 필요하면 모델이 공식 도구를 호출하며, 실제 결과만 근거로 사용해요.

## ✨ 何が起きたのか

| なし | insane-search あり |
| :--- | :--- |
| 普通のフェッチが `403` に当たり、Claude が読めないと言う | プラグインが公開アクセスルートを選び、使えるテキストを返す |
| ミラー・アーカイブ・モバイル URL を手で試す羽目に | フォールバックが自動で段階を上げる、しかも公開ルートのみ |
| ブロックされたページは行き止まり | メタデータと構造化データからタイトル・価格・要約は得られる |

## 🔁 仕組み

HTTP Phase 0~3 수집과 진단을 유지하고 외부 브라우저 호출은 모델에 인계해요. 엔진은 브라우저나 MCP 서버를 설치하지 않아요.

<details>
<summary><strong>Phase 0→3 アダプティブスケジューラ —— 詳細</strong></summary>

各フェーズは、前のフェーズが失敗するかブロック信号を検知したときだけ実行されます：

- **Phase 0** —— 汎用チェーンが自力で見つけられない公式公開エンドポイント（プラットフォーム API、フィード）
- **Phase 1** —— 軽量プローブ：公開 API リーダー、シンジケーションゲートウェイ、モバイル / `.json` / `/rss` の URL バリアント
- **Phase 2** —— TLS なりすまし（curl_cffi：safari → chrome → firefox）+ 完全なブラウザ ID
- **브라우저 인계** — HTTP 수집으로 본문을 얻지 못하고 `needs_browser=true`이면 모델이 공식 `browser_use`를 호출해요. HTTP 성공은 `needs_browser=false`예요.
- **Exit** —— ログインやペイウォールを検知：装わず *"authentication required"* と報告する

すべての応答は OGP / JSON-LD でもスキャンされるため、断片的なページでもタイトル・要約・価格は得られます。
</details>

## 🔒 境界（Boundaries）

insane-search は**公開コンテンツのリーダー**であり、認証を回避する手段ではありません。

- 公開ページ・公開 API・フィード・アーカイブ・ブラウザの公開応答で届く範囲に到達します。
- **인증·CAPTCHA·보안 확인·접근 차단에서 멈춰요** — 브라우저에서도 우회하지 않아요.
- あなたの代わりにログインせず、認証情報を保存も送信もしません。
- すべてのルートは認証不要の公開エンドポイントと、標準的で文書化された手法のみを使います。

## ライセンス

MIT

---

<div align="center">

**[gptaku-plugins](https://github.com/fivetaku/gptaku_plugins) の一部** —— 他のすべてが止まる壁を突き破る Claude Code プラグイン集。

</div>
