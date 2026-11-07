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
    fun `엔진 실패는 본문 없이 사유와 미시도 경로를 보존해요`() = runBlocking {
        val payload = """
            {"ok":false,"verdict":"error","summary":"browser_use로 확인해 주세요.","stop_reason":"browser_use가 필요해요.","stderr":"HTTP 403",
             "untrusted_text":"[BEGIN UNTRUSTED WEB CONTENT]\n\n[END UNTRUSTED WEB CONTENT]","untried_routes":["browser_use"],"needs_browser":true}
        """.trimIndent()
        val plugin = InsaneSearchPlugin()
        plugin.ensureReady(hostForFetch(payload)).getOrThrow()

        val rescue = plugin.fetchPage("https://example.com/", 1_000, 540).getOrThrow()

        assertEquals("", rescue.text)
        assertEquals(UNVERIFIED_LAYER, rescue.layer)
        assertTrue(rescue.verdict.contains("browser_use가 필요해요."))
        assertTrue(rescue.verdict.contains("browser_use로 확인해 주세요."))
        assertEquals(listOf("browser_use"), rescue.untriedRoutes)
        assertTrue(rescue.needsBrowser)
    }

    @Test
    fun `비정상 종료와 빈 본문은 검증된 성공이 아니에요`() = runBlocking {
        for ((payload, exitCode) in listOf(
            """{"ok":true,"verdict":"strong_ok","untrusted_text":"본문"}""" to 1,
            """{"ok":true,"verdict":"strong_ok","untrusted_text":"   "}""" to 0,
        )) {
            val plugin = InsaneSearchPlugin()
            plugin.ensureReady(hostForFetch(payload, exitCode)).getOrThrow()
            val rescue = plugin.fetchPage("https://example.com/", 1_000, 540).getOrThrow()
            assertEquals(UNVERIFIED_LAYER, rescue.layer)
            assertTrue(rescue.text.isBlank())
        }
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
    fun `잘못된 URL은 실행하지 않고 제한 시간은 지원 범위로 맞춰요`() = runBlocking {
        val host = hostForFetch("""{"ok":true,"untrusted_text":"본문"}""")
        val plugin = InsaneSearchPlugin()
        plugin.ensureReady(host).getOrThrow()

        assertTrue(plugin.fetchPage("file:///etc/passwd", 1_000, 540).isFailure)
        assertTrue(plugin.fetchPage("https://example.com/\nrm -rf /", 1_000, 540).isFailure)
        assertTrue(plugin.fetchPage("   ", 1_000, 540).isFailure)
        assertEquals(1, host.commands.size)

        plugin.fetchPage("https://example.com/", 10, 1).getOrThrow()
        assertEquals(15, host.timeouts.last())

        plugin.fetchPage("https://example.com/", 99_999, 5_000).getOrThrow()
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
