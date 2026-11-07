import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

val pluginRepository = projectDir.parentFile
val pluginVersion = pluginRepository.resolve("VERSION").readText().trim()
version = pluginVersion
val apiPin = Properties().apply {
    pluginRepository.resolve("plugin-api.lock").inputStream().use { load(it) }
}

android {
    namespace = "com.sleepysoong.logent.insanesearch"
    compileSdk = 37

    defaultConfig {
        minSdk = 26
        buildConfigField("String", "PLUGIN_VERSION", "\"$pluginVersion\"")
    }

    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

// 실행 자산은 APK 하나에 ZIP으로 넣어요. argv 한도를 피하려고 플러그인이 APK 경로와 unzip을 써요.
val repositoryRoot = projectDir.parentFile
val engineZip = tasks.register<Zip>("insaneSearchEngineZip") {
    from(repositoryRoot.resolve("skills/insane-search")) {
        include(
            "engine/**",
            "SKILL.md",
            "LICENSE",
            "LOGENT-NOTICE.md",
            "DISCLAIMER.md",
            "UPSTREAM_COMMIT",
        )
        exclude("engine/tests/**", "engine/templates/**", "**/package.json", "**/node_modules/**", "**/__pycache__/**", "**/*.pyc")
    }
    from(repositoryRoot) {
        include("LICENSE", "DISCLAIMER.md", "UPSTREAM_COMMIT")
    }
    archiveFileName.set("engine.zip")
    destinationDirectory.set(layout.buildDirectory.dir("generated/pluginAssets/plugins/insane-search"))
}

val stagedAssets = tasks.register<Sync>("stagePluginAssets") {
    dependsOn(engineZip)
    from(layout.buildDirectory.dir("generated/pluginAssets"))
    into(layout.buildDirectory.dir("staged/pluginAssets"))
}
// AGP 9 레거시 라이브러리 getter의 하위 타입 대신 공통 source-set 계약으로 접근해요.
extensions.getByType<com.android.build.gradle.BaseExtension>().sourceSets.getByName("main").assets.setSrcDirs(
    listOf(layout.buildDirectory.dir("staged/pluginAssets")),
)
apply(from = pluginRepository.resolve("scripts/artifacts.gradle.kts"))

// 자산 ZIP이 없으면 APK에 빈 plugin 자산이 들어가므로 mergeAssets가 반드시 이 태스크를 기다려요.
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }.configureEach {
    dependsOn(stagedAssets)
}
// Lint 모델도 생성 자산을 읽으므로 태스크 순서를 명시해요.
tasks.matching { it.name.contains("Lint", ignoreCase = true) }.configureEach {
    dependsOn(stagedAssets)
}

dependencies {
    implementation("${apiPin.getProperty("group")}:${apiPin.getProperty("artifact")}:${apiPin.getProperty("version")}")
    testImplementation("junit:junit:4.13.2")
}

tasks.withType<Test>().configureEach {
    dependsOn(stagedAssets)
    // 파이썬 엔진 테스트와 자산 원본을 저장소 기준 경로로 찾아요.
    systemProperty("logent.repo.root", repositoryRoot.absolutePath)
    systemProperty(
        "logent.plugin.assets",
        layout.buildDirectory.dir("staged/pluginAssets").get().asFile.absolutePath,
    )
    maxParallelForks = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
}
