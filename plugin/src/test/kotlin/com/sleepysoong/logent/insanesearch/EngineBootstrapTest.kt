package com.sleepysoong.logent.insanesearch

import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/** 실제 배포 셸을 실행하고 외부 설치와 모듈 상태만 격리해요. */
class EngineBootstrapTest {
    @Test
    fun `기존 배포에서도 사라진 의존성을 복구한 뒤 준비돼요`() = runBlocking {
        fixture { home, command ->
            val result = execute(home, command)
            assertEquals(result.second, 0, result.first)
            assertTrue(result.second.contains(READY_MARKER))
            val installs = File(home, "installs").readLines()
            assertEquals(2, installs.size)
            assertTrue(installs[0].contains("setuptools"))
            assertTrue(installs[1].contains("curl_cffi>=0.17.0"))
            assertTrue(installs[1].contains("cffi>=2.1.1"))
            assertTrue(installs[1].contains("--force-reinstall"))
            assertTrue(installs[1].contains("--no-binary=cffi"))
            assertFalse(installs.any { it.contains("--upgrade pip") })
            assertEquals(ENGINE_VERSION, File(home, ".logent/plugins/insane-search/VERSION").readText())
            val again = execute(home, command)
            assertEquals(again.second, 0, again.first)
            assertEquals(installs, File(home, "installs").readLines())
        }
    }

    @Test
    fun `일반 CPython은 Android 빌드 전제 없이 복구해요`() = runBlocking {
        fixture { home, command ->
            File(home, "nonandroid").writeText("")
            val result = execute(home, command)
            assertEquals(result.second, 0, result.first)
            assertTrue(result.second.contains(READY_MARKER))
            val installs = File(home, "installs").readLines()
            assertEquals(1, installs.size)
            assertTrue(installs.single().contains("curl_cffi>=0.17.0"))
            assertFalse(installs.single().contains("--no-binary"))
        }
    }

    @Test
    fun `설치 실패 진단은 제한하고 비밀은 가려요`() = runBlocking {
        fixture { home, command ->
            File(home, "fail-install").writeText("")
            val result = execute(home, command)
            assertTrue(result.first != 0)
            assertTrue(result.second.contains("INSANE_SEARCH_DEPS_FAILED"))
            assertTrue(result.second.contains("설치 오류를 확인해 주세요."))
            assertFalse(result.second.contains("secret-fixture-token"))
            assertFalse(result.second.contains(READY_MARKER))
            assertTrue(result.second.length < 4_000)
        }
    }

    private suspend fun fixture(block: (File, String) -> Unit) {
        val python = runCatching {
            ProcessBuilder("python3", "-c", "import sys; print(sys.executable)").start()
                .let { process ->
                    val path = process.inputStream.bufferedReader().readText().trim()
                    if (process.waitFor() == 0) path else null
                }
        }.getOrNull()
        assumeTrue("python3가 없어 배포 회귀를 건너뛰어요.", python != null)
        assumeTrue("Termux 실기기에서는 호스트 격리 회귀를 건너뛰어요.", !File("/data/data/com.termux/files/usr/bin/python3").exists())
        val home = Files.createTempDirectory("insane-bootstrap-").toFile()
        try {
            val bin = File(home, "bin").apply { mkdirs() }
            File(bin, "python3").apply {
                writeText("#!/bin/sh\nexec '$python' \"\$@\"\n")
                setExecutable(true)
            }
            File(bin, "clang").apply { writeText("#!/bin/sh\nexit 0\n"); setExecutable(true) }
            File(bin, "pkg-config").apply { writeText("#!/bin/sh\nexit 0\n"); setExecutable(true) }
            File(home, "sitecustomize.py").writeText(sitecustomize)
            val host = FakePluginHost(apkPath = "/fixture/plugin.apk")
            EngineRuntime().ensureReady(host).getOrThrow()
            val dir = File(home, ".logent/plugins/insane-search").apply { mkdirs() }
            File(dir, "engine").mkdirs()
            File(dir, "engine/__main__.py").writeText("")
            File(dir, "VERSION").writeText(ENGINE_VERSION)
            val identity = MessageDigest.getInstance("SHA-256")
                .digest("${host.apkPath}\u0000${host.appVersion}".toByteArray())
                .joinToString("") { "%02x".format(it.toInt() and 0xff) }
            File(dir, "CONTENT").writeText(identity)
            block(home, host.commands.single())
        } finally {
            home.deleteRecursively()
        }
    }

    private fun execute(home: File, command: String): Pair<Int, String> {
        val process = ProcessBuilder("sh", "-c", command).apply {
            environment()["HOME"] = home.path
            environment()["PATH"] = File(home, "bin").path + ":" + System.getenv("PATH")
            environment()["PYTHONPATH"] = home.path
            environment()["FIXTURE_API_TOKEN"] = "secret-fixture-token"
            redirectErrorStream(true)
        }.start()
        val output = process.inputStream.bufferedReader().readText()
        val finished = process.waitFor(30, TimeUnit.SECONDS)
        if (!finished) process.destroyForcibly()
        assertTrue("배포 셸이 끝나지 않았어요.", finished)
        return process.exitValue() to output
    }

    private val sitecustomize = """
        import builtins, importlib, importlib.metadata, os, pathlib, subprocess, sys, types
        home = pathlib.Path(os.environ['HOME'])
        sys.platform = 'linux' if (home / 'nonandroid').exists() else 'android'
        modules = {'cffi', '_cffi_backend', 'curl_cffi', 'curl_cffi.requests', 'bs4', 'yaml', 'pypdf', 'markdownify', 'yt_dlp'}
        original_import = builtins.__import__
        original_module = importlib.import_module
        original_run = subprocess.run
        def module(name):
            if not (home / 'installed').exists():
                raise ModuleNotFoundError(name)
            obj = types.ModuleType(name)
            obj.__path__ = []
            return obj
        def importing(name, *args, **kwargs):
            return module(name) if name in modules else original_import(name, *args, **kwargs)
        builtins.__import__ = importing
        importlib.import_module = lambda name, *args: module(name) if name in modules else original_module(name, *args)
        importlib.metadata.version = lambda name: '2.1.1' if name == 'cffi' else '0.17.0'
        def run(args, **kwargs):
            if args[1:4] == ['-m', 'pip', 'install']:
                with (home / 'installs').open('a') as log:
                    log.write(' '.join(args[1:]) + '\n')
                if (home / 'fail-install').exists():
                    kwargs['stdout'].write(('x' * 16000 + '\n설치 오류를 확인해 주세요. secret-fixture-token https://user:pass@example.com/?token=hidden\n').encode())
                    return subprocess.CompletedProcess(args, 1)
                if any(item.startswith('curl_cffi') for item in args):
                    (home / 'installed').touch()
                return subprocess.CompletedProcess(args, 0)
            return original_run(args, **kwargs)
        subprocess.run = run
    """.trimIndent()
}
