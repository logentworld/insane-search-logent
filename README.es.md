[English](README.md) | [한국어](README.ko.md) | [中文](README.zh.md) | [日本語](README.ja.md) | Español

<div align="center">

# insane-search

**Impossible is nothing. Si es público, insane-search acaba entrando.**

Un lector de páginas públicas resistente al bloqueo, para Claude Code. Sin claves de API, sin configurar proxies.

<p>
  <a href="https://docs.anthropic.com/en/docs/claude-code"><img src="https://img.shields.io/badge/platform-Claude_Code-D97757?logo=claude" alt="Claude Code"></a>
  <img src="https://img.shields.io/badge/API_key-not_required-3FB950" alt="No API key">
  <a href="https://github.com/fivetaku/gptaku_plugins"><img src="https://img.shields.io/badge/part_of-gptaku--plugins-6E56CF" alt="part of gptaku-plugins"></a>
  <a href="https://github.com/fivetaku/insane-search/stargazers"><img src="https://img.shields.io/github/stars/fivetaku/insane-search?style=flat&color=F0B72F" alt="stars"></a>
</p>

<!-- Hero — cinematic key-art: a blocked site (403 / CAPTCHA / WAF) shatters as
     insane-search breaks through and returns real public content with its source. -->
<img src="assets/hero.png" width="860" alt="División cinematográfica: a la izquierda un sitio bloqueado muestra 403 Forbidden, un CAPTCHA y un muro WAF; se rompe por el centro mientras insane-search atraviesa por la derecha y devuelve una publicación pública real de @claudeai (Claude Code Plugins) con su fuente, sin clave de API.">

</div>

---

## Novedades de v0.16.3

- **Contenido y trace en una sola consulta:** `--json-content` devuelve juntos los metadatos, el trace y el texto delimitado como contenido no confiable, sin volver a consultar la misma URL para obtener el diagnóstico. La salida de `--json` sigue sin incluir el cuerpo.
- **Carga diferida de analizadores PDF:** `pdfplumber` y `pypdf` solo se cargan cuando hace falta extraer un PDF, no al iniciar el motor para HTML. Se mantienen la extracción de PDF y el comportamiento de respaldo.

## ⚡ Instalación

```bash
/plugin marketplace add https://github.com/fivetaku/gptaku_plugins.git
/plugin install insane-search@gptaku-plugins
/reload-plugins
```

No hay comandos que aprender. Habla con Claude Code como siempre: insane-search entra en acción en cuanto una petición se bloquea.

## 💬 Pruébalo

Solo pídelo con normalidad: insane-search se activa cuando algo se bloquea:

> *"Busca qué dice la gente sobre Claude Code en Reddit y resume los hilos más populares."*
> *"Busca en X publicaciones sobre insane-search."*
> *"Resume este vídeo de YouTube."*

**Resultado esperado:** Claude llega a la ruta pública de cada sitio —el feed de Reddit, X mediante búsqueda gratuita en Brave/Yahoo más validación con tweet-result, los subtítulos de YouTube— sin inicio de sesión ni clave de API, y devuelve texto utilizable, allí donde la misma petición respondería *"no puedo acceder a eso"* sin el plugin. Si ya hay credenciales de xAI disponibles, la búsqueda de X por palabras clave se complementa automáticamente con `x_search` nativo; la ruta gratuita sigue activa y puede forzarse con `INSANE_SEARCH_XAI=off`.

## 🌐 Funciona en

**X · Reddit · YouTube · Hacker News · Naver · Coupang · LinkedIn · Medium · Substack · arXiv · GitHub · Stack Overflow · Bluesky · Mastodon** —además de cualquier sitio con una página pública, un feed o `/rss`. Lista completa de plataformas y métodos → [PLATFORMS.md](PLATFORMS.md).

## ⚙️ Por qué lo consigue

- **HTTP 수집과 브라우저를 분리해요** — 공개 API·피드와 HTTP Phase 0~3 경로를 먼저 사용해요.
- **로컬 브라우저는 실행하지 않아요** — 옵션 생략과 `enable_playwright=True`도 HTTP-only예요. `--no-playwright`는 호환 스위치예요.
- **모델이 공식 도구를 호출해요** — `needs_browser=true`, `untried_routes=["browser_use"]`이면 모델이 `sleepysoong:browser_use`의 `browser_use`로 공개 페이지를 확인해요.
- **Cero configuración** —instala lo que necesita (`curl_cffi`, `yt-dlp`, …) en el primer uso. Sin claves de API, sin registro.

## 🆚 Claude Code por defecto vs `+ insane-search`

| Cuando te topas con… | Claude Code solo | `+ insane-search` |
| :--- | :--- | :--- |
| 공개 페이지의 HTTP 403 | 수집에 실패할 수 있어요. | HTTP 진단을 반환하고 필요하면 모델이 공식 `browser_use`를 호출해요. |
| Contenido de plataformas (X, Reddit, HN) | ✖ a menudo bloqueado o vacío | ✓ lectores de API públicas + sindicación |
| CAPTCHA·보안 확인·접근 차단 | 중단해요. | 우회하지 않고 수집 한계를 알려요. |
| Una página multimedia (YouTube, 1.800+ sitios) | ✖ sin transcripción | ✓ metadatos `yt-dlp` + subtítulos |
| Herramientas que faltan (`curl_cffi`, `yt-dlp`) | — | ✓ se instalan solas en el primer uso |
| Claves de API / registro | — | ✓ ninguno |
| Un **muro de login o de pago** | ✖ | ✖ **se detiene aquí, y lo dice** (ver Límites) |

HTTP 예외·빈 본문·오류 응답은 성공으로 바꾸지 않아요. 브라우저가 필요하면 모델이 공식 도구를 호출하며, 실제 결과만 근거로 사용해요.

## ✨ Qué acaba de pasar

| Sin él | Con insane-search |
| :--- | :--- |
| Un fetch normal choca con `403` y Claude dice que no puede leer la página | El plugin elige una ruta de acceso público y devuelve texto utilizable |
| Pruebas a mano espejos, archivos, URLs móviles | Los fallbacks escalan solos, siempre por rutas públicas |
| Una página bloqueada es un callejón sin salida | Los metadatos y datos estructurados aún dan títulos, precios y resúmenes |

## 🔁 Cómo funciona

HTTP Phase 0~3 수집과 진단을 유지하고 외부 브라우저 호출은 모델에 인계해요. 엔진은 브라우저나 MCP 서버를 설치하지 않아요.

<details>
<summary><strong>Planificador adaptativo Phase 0→3 — detalles</strong></summary>

Cada fase se ejecuta solo si la anterior falla o detecta una señal de bloqueo:

- **Phase 0** — endpoints públicos oficiales (APIs de plataforma, feeds) que la cadena genérica no puede descubrir por sí sola
- **Phase 1** — sondas ligeras: lectores de API públicas, pasarelas de sindicación, variantes de URL móvil / `.json` / `/rss`
- **Phase 2** — suplantación TLS (curl_cffi: safari → chrome → firefox) con una identidad de navegador completa
- **브라우저 인계** — HTTP 수집으로 본문을 얻지 못하고 `needs_browser=true`이면 모델이 공식 `browser_use`를 호출해요. HTTP 성공은 `needs_browser=false`예요.
- **Exit** — se detecta un login o muro de pago: informa *"authentication required"* en lugar de fingir

Cada respuesta también se escanea en busca de OGP / JSON-LD, así que incluso las páginas parciales dan títulos, resúmenes y precios.
</details>

## 🔒 Límites (Boundaries)

insane-search es un **lector de contenido público**, no una forma de saltarse la autenticación.

- Alcanza lo disponible a través de páginas públicas, APIs públicas, feeds, archivos y las respuestas públicas de un navegador.
- **인증·CAPTCHA·보안 확인·접근 차단에서 멈춰요** — 브라우저에서도 우회하지 않아요.
- Nunca inicia sesión por ti y nunca almacena ni transmite credenciales.
- Todas las rutas usan endpoints públicos sin autenticación y técnicas estándar y documentadas.

## Licencia

MIT

---

<div align="center">

**Parte de [gptaku-plugins](https://github.com/fivetaku/gptaku_plugins)** — plugins de Claude Code que atraviesan los muros donde todo lo demás se detiene.

</div>
