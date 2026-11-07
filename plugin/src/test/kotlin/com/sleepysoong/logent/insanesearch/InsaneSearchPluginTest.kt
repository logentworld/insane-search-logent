package com.sleepysoong.logent.insanesearch

import com.sleepysoong.logent.plugin.PageRescueService
import com.sleepysoong.logent.plugin.ProcessResult
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InsaneSearchPluginTest {

    private fun host(
        apkPath: String = "/data/app/~~abc/com.sleepysoong.logent-1/base.apk",
        respond: (String) -> Result<ProcessResult> = {
            Result.success(ProcessResult(0, "INSANE_SEARCH_DEPLOYED", false))
        },
    ) = FakePluginHost(apkPath = apkPath).also { it.respond = respond }

    private fun hostForFetch(payload: String, exitCode: Int = 0): FakePluginHost = host { command ->
        if (command.contains("-m engine")) {
            Result.success(ProcessResult(exitCode, payload, false))
        } else {
            Result.success(ProcessResult(0, "INSANE_SEARCH_DEPLOYED", false))
        }
    }

    @Test
    fun `플러그인은 도구 없이 구조 서비스만 제공해요`() {
        val plugin = InsaneSearchPlugin()
        assertEquals("com.sleepysoong.logent.insane-search", plugin.id)
        assertEquals(BuildConfig.PLUGIN_VERSION, plugin.version)
        assertTrue(plugin.tools().isEmpty())
        assertEquals(1, plugin.services().size)
        assertTrue(plugin.services().single() is PageRescueService)
    }

    @Test
    fun `ensureReady는 APK 경로와 unzip으로 자산을 원자 교체해요`() = runBlocking {
        val host = host(apkPath = "/data/app/base apk.apk")
        val plugin = InsaneSearchPlugin()

        assertTrue(plugin.ensureReady(host).isSuccess)
        val command = host.commands.single()

        assertTrue(command.contains("APK='/data/app/base apk.apk'"))
        assertTrue(command.contains("unzip -p \"\$APK\" 'assets/plugins/insane-search/engine.zip'"))
        assertTrue(command.contains("HOME/.logent/plugins/insane-search"))
        assertTrue(command.contains("engine/__main__.py"))
        assertTrue(command.contains("'curl_cffi>=0.15.0' beautifulsoup4 pyyaml pypdf markdownify yt-dlp"))
        assertTrue(command.contains("--user"))
        assertTrue(command.contains("> \"\$DIR/VERSION\""))
        assertTrue(command.contains(ENGINE_VERSION))
        assertTrue(command.contains("\"\$DIR/engine.old\""))
        assertFalse(command.contains("base64"))
        assertEquals(900, host.timeouts.single())

        val versionWrite = command.indexOf("> \"\$DIR/VERSION\"")
        val depsGate = command.lastIndexOf("INSANE_SEARCH_DEPS_FAILED")
        assertTrue("VERSION은 의존성 확인 뒤에 기록해야 해요", versionWrite > depsGate)
    }

    @Test
    fun `이미 배포된 버전이면 같은 명령을 다시 실행하지 않아요`() = runBlocking {
        val host = host()
        val plugin = InsaneSearchPlugin()

        plugin.ensureReady(host).getOrThrow()
        plugin.ensureReady(host).getOrThrow()

        assertEquals(1, host.commands.size)
    }

    @Test
    fun `배포 실패는 이유를 남기고 다음 호출에서 다시 시도해요`() = runBlocking {
        var attempts = 0
        val host = host {
            attempts++
            Result.success(ProcessResult(78, "INSANE_SEARCH_PYTHON_MISSING", false))
        }
        val plugin = InsaneSearchPlugin()

        val ready = plugin.ensureReady(host)
        assertTrue(ready.isFailure)
        assertTrue(ready.exceptionOrNull()?.message.orEmpty().contains("INSANE_SEARCH_PYTHON_MISSING"))

        val fetched = plugin.fetchPage("https://example.com/", 1_000, 540)
        assertTrue(fetched.isFailure)
        assertEquals(2, attempts)
    }

    @Test
    fun `셸 자체가 실패하면 그 오류를 그대로 돌려줘요`() = runBlocking {
        val host = host { Result.failure(IllegalStateException("Termux 연결 실패")) }
        val plugin = InsaneSearchPlugin()

        val ready = plugin.ensureReady(host)
        assertTrue(ready.isFailure)
        assertEquals("Termux 연결 실패", ready.exceptionOrNull()?.message)
    }

    @Test
    fun `엔진 JSON의 본문과 진단 정보를 WebRescue로 돌려줘요`() = runBlocking {
        val payload = """
            {"ok":true,"verdict":"weak_ok","final_url":"https://example.com/","summary":"성공",
             "prompt_injection_risk":"low","untrusted_text":"본문","untried_routes":[],
             "must_invoke_playwright_mcp":false}
        """.trimIndent()
        val host = hostForFetch(payload)
        val plugin = InsaneSearchPlugin()
        plugin.ensureReady(host).getOrThrow()

        val rescue = plugin.fetchPage("https://example.com/", 1_000, 540).getOrThrow()

        assertEquals("본문", rescue.text)
        assertEquals("weak_ok", rescue.verdict)
        assertEquals(LAYER, rescue.layer)
        assertFalse(rescue.needsBrowser)
        assertTrue(rescue.untriedRoutes.isEmpty())
        assertEquals(null, rescue.status)

        val command = host.commands.last()
        assertTrue(command.contains("python3 -m engine 'https://example.com/'"))
        assertTrue(command.contains("--json-content --no-playwright"))
        assertTrue(command.contains("--max-attempts 24"))
        assertTrue(command.contains("BRAVE_SEARCH_API_KEY=''"))
        assertTrue(command.contains("INSANE_SEARCH_XAI=off"))
        assertTrue(command.contains("'1000' <<'PY'"))
        assertEquals(540, host.timeouts.last())
    }

    @Test
    fun `엔진 실패는 본문 없이 사유와 미시도 경로를 보존해요`() = runBlocking {
        val payload = """
            {"ok":false,"verdict":"error","summary":"차단됨","stderr":"HTTP 403",
             "untrusted_text":"","untried_routes":["playwright"],"must_invoke_playwright_mcp":true}
        """.trimIndent()
        val plugin = InsaneSearchPlugin()
        plugin.ensureReady(hostForFetch(payload, exitCode = 1)).getOrThrow()

        val rescue = plugin.fetchPage("https://example.com/", 1_000, 540).getOrThrow()

        assertEquals("", rescue.text)
        assertEquals(UNVERIFIED_LAYER, rescue.layer)
        assertEquals("error", rescue.verdict)
        assertEquals(listOf("playwright"), rescue.untriedRoutes)
        assertTrue(rescue.needsBrowser)
    }

    @Test
    fun `해석할 수 없는 출력은 실패 Result로 돌려줘요`() = runBlocking {
        val plugin = InsaneSearchPlugin()
        plugin.ensureReady(hostForFetch("python3: traceback", exitCode = 1)).getOrThrow()

        val rescue = plugin.fetchPage("https://example.com/", 1_000, 540)

        assertTrue(rescue.isFailure)
        assertTrue(rescue.exceptionOrNull()?.message.orEmpty().contains("해석하지 못했어요"))
        assertTrue(rescue.exceptionOrNull()?.message.orEmpty().contains("traceback"))
    }

    @Test
    fun `종료 코드 78은 배포 오류 메시지로 돌려줘요`() = runBlocking {
        val plugin = InsaneSearchPlugin()
        plugin.ensureReady(hostForFetch("INSANE_SEARCH_NOT_DEPLOYED", exitCode = 78)).getOrThrow()

        val rescue = plugin.fetchPage("https://example.com/", 1_000, 540)

        assertTrue(rescue.isFailure)
        assertEquals("INSANE_SEARCH_NOT_DEPLOYED", rescue.exceptionOrNull()?.message)
    }

    @Test
    fun `URL과 글자 수 한도를 실행 전에 검증해요`() = runBlocking {
        val host = hostForFetch("""{"ok":true,"untrusted_text":"본문"}""")
        val plugin = InsaneSearchPlugin()
        plugin.ensureReady(host).getOrThrow()

        assertTrue(plugin.fetchPage("file:///etc/passwd", 1_000, 540).isFailure)
        assertTrue(plugin.fetchPage("https://example.com/\nrm -rf /", 1_000, 540).isFailure)
        assertTrue(plugin.fetchPage("   ", 1_000, 540).isFailure)
        assertEquals(1, host.commands.size)

        plugin.fetchPage("https://example.com/", 10, 1).getOrThrow()
        assertTrue(host.commands.last().contains("'1000' <<'PY'"))
        assertEquals(15, host.timeouts.last())

        plugin.fetchPage("https://example.com/", 99_999, 5_000).getOrThrow()
        assertTrue(host.commands.last().contains("'26000' <<'PY'"))
        assertEquals(900, host.timeouts.last())
    }

    @Test
    fun `준비 전에는 서비스가 명확한 오류를 돌려줘요`() = runBlocking {
        val plugin = InsaneSearchPlugin()

        val rescue = plugin.fetchPage("https://example.com/", 1_000, 540)

        assertTrue(rescue.isFailure)
        assertTrue(rescue.exceptionOrNull()?.message.orEmpty().contains("준비되지 않았어요"))
    }
}
