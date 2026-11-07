package com.sleepysoong.logent.insanesearch

import com.sleepysoong.logent.plugin.PluginHost
import com.sleepysoong.logent.plugin.WebRescue
import com.sleepysoong.logent.plugin.shellQuote
import java.security.MessageDigest
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** 엔진 배포 위치와 실행 자산 이름. Termux 홈 기준 상대 경로예요. */
internal const val ENGINE_VERSION = "ead12c51633fa1e00ca8a048203da2439feb950e"
internal const val ENGINE_DIR = "plugins/insane-search"
internal const val ENGINE_ASSET_ENTRY = "assets/plugins/insane-search/engine.zip"
internal const val DEPLOY_TIMEOUT_SECONDS = 900
internal const val MAX_TOOL_TEXT = 26_000
internal const val MIN_MAX_CHARS = 1_000
internal const val MIN_TIMEOUT_SECONDS = 15
internal const val MAX_TIMEOUT_SECONDS = 900
internal const val LAYER = "insane-search"
internal const val UNVERIFIED_LAYER = "insane-search(미확인)"
internal const val DEPLOYED_MARKER = "INSANE_SEARCH_DEPLOYED"
internal const val READY_MARKER = "INSANE_SEARCH_READY"

/**
 * Termux에 내장한 insane-search 엔진의 배포와 호출을 맡아요.
 *
 * 콘텐츠 아카이브 자산은 argv 한도를 피하려고 `unzip -p`로 꺼내요.
 * 임시 디렉터리에 풀어 엔진 레이아웃과 Python 의존성을 검증한 뒤 원자 교체하고,
 * 마지막에만 VERSION을 기록해 실패한 배포가 성공으로 굳지 않게 해요.
 */
internal class EngineRuntime(private val engineVersion: String = ENGINE_VERSION) {
    private val mutex = Mutex()
    private val json = Json { ignoreUnknownKeys = true }

    @Volatile
    private var host: PluginHost? = null

    @Volatile
    private var ready = false

    suspend fun ensureReady(host: PluginHost): Result<Unit> = mutex.withLock {
        this.host = host
        if (ready) return@withLock Result.success(Unit)
        val archive = host.contentArchive("plugins/insane-search")
            .getOrElse { return@withLock Result.failure(it) }
        if (archive.isBlank()) {
            return@withLock Result.failure(IllegalStateException("콘텐츠 아카이브 경로가 비어 있어요."))
        }
        val identity = MessageDigest.getInstance("SHA-256")
            .digest("$archive\u0000${host.appVersion}".toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
        val executed = host.shell(deployCommand(archive, identity), DEPLOY_TIMEOUT_SECONDS)
            .getOrElse { return@withLock Result.failure(it) }
        val output = executed.output
        if (!executed.success || (!output.contains(DEPLOYED_MARKER) && !output.contains(READY_MARKER))) {
            return@withLock Result.failure(IllegalStateException(failureReason(output)))
        }
        ready = true
        Result.success(Unit)
    }

    suspend fun fetchPage(
        url: String,
        maxChars: Int,
        timeoutSeconds: Int,
    ): Result<WebRescue> {
        val target = url.trim()
        if (target.isEmpty()) return Result.failure(IllegalArgumentException("읽을 URL이 필요해요."))
        if (!target.startsWith("https://") && !target.startsWith("http://")) {
            return Result.failure(IllegalArgumentException("http(s) URL만 insane-search로 읽을 수 있어요."))
        }
        if (target.any { it == '\n' || it == '\r' || it == '\u0000' }) {
            return Result.failure(IllegalArgumentException("URL에 줄바꿈이나 NUL을 넣을 수 없어요."))
        }
        val activeHost = host
            ?: return Result.failure(IllegalStateException("insane-search 플러그인이 아직 준비되지 않았어요."))
        ensureReady(activeHost).onFailure { return Result.failure(it) }
        val limit = maxChars.coerceIn(MIN_MAX_CHARS, MAX_TOOL_TEXT)
        val timeout = timeoutSeconds.coerceIn(MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
        val executed = activeHost.shell(fetchCommand(target, limit), timeout)
            .getOrElse { return Result.failure(it) }
        return parse(executed.exitCode, executed.output)
    }

    private fun parse(exitCode: Int, output: String): Result<WebRescue> {
        if (exitCode == 78) {
            return Result.failure(
                IllegalStateException(output.trim().ifBlank { "insane-search를 실행할 수 없어요." }),
            )
        }
        val raw = output.trim()
        val start = raw.indexOf('{')
        val jsonText = if (start >= 0) {
            val end = raw.lastIndexOf('}')
            if (end > start) raw.substring(start, end + 1) else null
        } else {
            null
        }
        val payload = jsonText
            ?.let { runCatching { json.parseToJsonElement(it).jsonObject }.getOrNull() }
            ?: return Result.failure(
                IllegalStateException("insane-search 결과를 해석하지 못했어요: ${output.takeLast(300)}"),
            )
        val ok = payload.boolean("ok") ?: false
        val text = payload.string("untrusted_text").orEmpty()
        val verdict = payload.string("verdict").orEmpty()
            .ifBlank { payload.string("summary").orEmpty() }
        return Result.success(
            WebRescue(
                text = text,
                layer = if (ok && text.isNotBlank()) LAYER else UNVERIFIED_LAYER,
                status = null,
                verdict = verdict,
                untriedRoutes = payload.array("untried_routes").orEmpty().mapNotNull { element ->
                    runCatching { element.jsonPrimitive.contentOrNull }.getOrNull()
                },
                needsBrowser = payload.boolean("must_invoke_playwright_mcp") == true,
            ),
        )
    }

    private fun failureReason(output: String): String =
        output.lineSequence().firstOrNull { it.contains("INSANE_SEARCH_") }
            ?: output.lineSequence().lastOrNull { it.isNotBlank() }
            ?: "insane-search 배포에 실패했어요."

    private fun deployCommand(apkPath: String, identity: String): String = """
        |export PATH=/data/data/com.termux/files/usr/bin:${'$'}PATH
        |DIR="${'$'}HOME/.logent/plugins/insane-search"
        |mkdir -p "${'$'}DIR" || { echo "INSANE_SEARCH_DIR_FAILED"; exit 1; }
        |if [ "$(cat "${'$'}DIR/VERSION" 2>/dev/null)" = '$engineVersion' ] && [ "$(cat "${'$'}DIR/CONTENT" 2>/dev/null)" = '$identity' ] && [ -f "${'$'}DIR/engine/__main__.py" ]; then
        |  echo "$READY_MARKER"
        |  exit 0
        |fi
        |command -v python3 >/dev/null 2>&1 || { echo "INSANE_SEARCH_PYTHON_MISSING"; exit 78; }
        |command -v unzip >/dev/null 2>&1 || { echo "INSANE_SEARCH_UNZIP_MISSING"; exit 78; }
        |APK=${shellQuote(apkPath)}
        |STAGE=${'$'}(mktemp -d "${'$'}DIR/stage.XXXXXXXX") || { echo "INSANE_SEARCH_STAGE_FAILED"; exit 1; }
        |trap 'rm -rf "${'$'}STAGE"' EXIT
        |unzip -p "${'$'}APK" '$ENGINE_ASSET_ENTRY' > "${'$'}STAGE/engine.zip" 2>/dev/null || { echo "INSANE_SEARCH_ASSET_FAILED"; exit 1; }
        |[ -s "${'$'}STAGE/engine.zip" ] || { echo "INSANE_SEARCH_ASSET_EMPTY"; exit 1; }
        |python3 - "${'$'}STAGE/engine.zip" "${'$'}STAGE/unpacked" <<'PY'
        |import pathlib, sys, zipfile
        |archive = pathlib.Path(sys.argv[1])
        |stage = pathlib.Path(sys.argv[2])
        |stage.mkdir(parents=True, exist_ok=True)
        |try:
        |    with zipfile.ZipFile(archive) as z:
        |        for info in z.infolist():
        |            parts = pathlib.PurePosixPath(info.filename).parts
        |            if info.filename.startswith("/") or ".." in parts:
        |                raise SystemExit("unsafe zip path")
        |        z.extractall(stage)
        |except Exception as exc:
        |    print(f"INSANE_SEARCH_EXTRACT_FAILED: ${'$'}{exc}", file=sys.stderr)
        |    raise SystemExit(1)
        |PY
        |[ "${'$'}?" -eq 0 ] || { echo "INSANE_SEARCH_EXTRACT_FAILED"; exit 1; }
        |[ -f "${'$'}STAGE/unpacked/engine/__main__.py" ] || { echo "INSANE_SEARCH_LAYOUT_FAILED"; exit 1; }
        |check_deps() {
        |  python3 - <<'PY'
        |import importlib, importlib.metadata as metadata, re
        |for module in ("curl_cffi", "bs4", "yaml", "pypdf", "markdownify", "yt_dlp"):
        |    importlib.import_module(module)
        |version = tuple(int(x) for x in re.findall(r"\d+", metadata.version("curl_cffi"))[:2])
        |if version < (0, 15):
        |    raise SystemExit(f"curl_cffi too old: ${'$'}{version}")
        |PY
        |}
        |if ! check_deps >/dev/null 2>&1; then
        |  if ! python3 -m pip install --user -q 'curl_cffi>=0.15.0' beautifulsoup4 pyyaml pypdf markdownify yt-dlp >/dev/null 2>&1; then
        |    echo "INSANE_SEARCH_DEPS_FAILED"; exit 1
        |  fi
        |  check_deps >/dev/null 2>&1 || { echo "INSANE_SEARCH_DEPS_FAILED"; exit 1; }
        |fi
        |printf '%s' '$identity' > "${'$'}STAGE/CONTENT" || exit 1
        |# 첫 교체 전에 이전 표식을 무효화하고 마지막에만 새 표식을 원자 교체해요.
        |rm -f "${'$'}DIR/CONTENT" || exit 1
        |rm -rf "${'$'}DIR/engine.old"
        |if [ -d "${'$'}DIR/engine" ]; then mv "${'$'}DIR/engine" "${'$'}DIR/engine.old" || { echo "INSANE_SEARCH_REPLACE_FAILED"; exit 1; }; fi
        |if ! mv "${'$'}STAGE/unpacked/engine" "${'$'}DIR/engine"; then
        |  [ -d "${'$'}DIR/engine.old" ] && mv "${'$'}DIR/engine.old" "${'$'}DIR/engine"
        |  echo "INSANE_SEARCH_REPLACE_FAILED"; exit 1
        |fi
        |rm -rf "${'$'}DIR/engine.old"
        |for file in SKILL.md LICENSE LOGENT-NOTICE.md DISCLAIMER.md UPSTREAM_COMMIT; do
        |  [ -f "${'$'}STAGE/unpacked/${'$'}file" ] && cp -f "${'$'}STAGE/unpacked/${'$'}file" "${'$'}DIR/${'$'}file"
        |done
        |test -f "${'$'}DIR/engine/__main__.py" || { echo "INSANE_SEARCH_ENGINE_MISSING"; exit 1; }
        |printf '%s' '$engineVersion' > "${'$'}DIR/VERSION" || exit 1
        |mv -f "${'$'}STAGE/CONTENT" "${'$'}DIR/CONTENT" || exit 1
        |echo "$DEPLOYED_MARKER"
    """.trimMargin()

    private fun fetchCommand(url: String, limit: Int): String = """
        |export PATH=/data/data/com.termux/files/usr/bin:${'$'}PATH
        |DIR="${'$'}HOME/.logent/plugins/insane-search"
        |[ -f "${'$'}DIR/engine/__main__.py" ] || { echo "INSANE_SEARCH_NOT_DEPLOYED"; exit 78; }
        |command -v python3 >/dev/null 2>&1 || { echo "INSANE_SEARCH_PYTHON_MISSING"; exit 78; }
        |cd "${'$'}DIR" || { echo "INSANE_SEARCH_DIR_MISSING"; exit 78; }
        |export BRAVE_SEARCH_API_KEY=''
        |export INSANE_SEARCH_XAI=off
        |OUT=${'$'}(mktemp "${'$'}DIR/out.XXXXXX") || exit 1
        |ERR=${'$'}(mktemp "${'$'}DIR/err.XXXXXX") || exit 1
        |trap 'rm -f "${'$'}OUT" "${'$'}ERR"' EXIT
        |python3 -m engine ${shellQuote(url)} --json-content --no-playwright \
        |  --device auto --timeout 20 --max-attempts 24 >"${'$'}OUT" 2>"${'$'}ERR"
        |python3 - "${'$'}OUT" "${'$'}ERR" '$limit' <<'PY'
        |import json, pathlib, sys
        |out, err, limit = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
        |try:
        |    data = json.loads(out.read_text(encoding="utf-8"))
        |except Exception as exc:
        |    tail = err.read_text(encoding="utf-8", errors="replace")[-800:]
        |    print(json.dumps({"ok": False, "verdict": "error", "summary": f"엔진 출력을 해석하지 못했어요: ${'$'}{exc}", "stderr": tail}, ensure_ascii=False))
        |    raise SystemExit(0)
        |keep = {k: data.get(k) for k in (
        |    "ok", "verdict", "final_url", "summary", "prompt_injection_risk",
        |    "untried_routes", "must_invoke_playwright_mcp", "stop_reason",
        |)}
        |keep["untrusted_text"] = (data.get("untrusted_text") or "")[:limit]
        |if not keep.get("ok"):
        |    keep["stderr"] = err.read_text(encoding="utf-8", errors="replace")[-800:]
        |print(json.dumps(keep, ensure_ascii=False))
        |PY
    """.trimMargin()

    private fun JsonObject.string(name: String): String? =
        runCatching { this[name]?.jsonPrimitive?.contentOrNull }.getOrNull()

    private fun JsonObject.boolean(name: String): Boolean? =
        runCatching { this[name]?.jsonPrimitive?.booleanOrNull }.getOrNull()

    private fun JsonObject.array(name: String): JsonArray? =
        runCatching { this[name] as? JsonArray }.getOrNull()
}
