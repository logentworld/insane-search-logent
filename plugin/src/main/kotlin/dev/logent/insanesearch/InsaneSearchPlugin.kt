package dev.logent.insanesearch

import dev.logent.plugin.LogentPlugin
import dev.logent.plugin.PageRescueService
import dev.logent.plugin.PluginHost
import dev.logent.plugin.PluginService
import dev.logent.plugin.PluginTool
import dev.logent.plugin.WebRescue

/**
 * insane-search 엔진을 APK 자산으로 배포하고 `web_fetch` 구조 요청을 맡는 플러그인이에요.
 *
 * 모델에 노출하는 도구는 없어요. 직접 HTTP가 WAF에 막혔을 때 코어가
 * [PageRescueService]로만 호출하고, 엔진 실패는 서비스 `Result` 실패로 돌려줘요.
 */
class InsaneSearchPlugin : LogentPlugin, PageRescueService {
    override val id: String = "dev.logent.insane-search"
    override val name: String = "Insane Search"
    override val version: String = BuildConfig.PLUGIN_VERSION

    private val runtime = EngineRuntime()

    override fun tools(): List<PluginTool> = emptyList()

    override fun services(): List<PluginService> = listOf(this)

    override suspend fun ensureReady(host: PluginHost): Result<Unit> = runtime.ensureReady(host)

    override suspend fun fetchPage(
        url: String,
        maxChars: Int,
        timeoutSeconds: Int,
    ): Result<WebRescue> = runtime.fetchPage(url, maxChars, timeoutSeconds)
}
