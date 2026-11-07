# insane-search-logent

[fivetaku/insane-search](https://github.com/fivetaku/insane-search)를 포크해 Logent의
`web_fetch` 구조 경로와 `.lpg` 플러그인으로 묶은 저장소예요. 원본 이력과 원작자 고지를
그대로 유지하고, Logent에 필요한 변경만 `logent` 브랜치에 얹어요.

- 원본: `fivetaku/insane-search` v0.17.4 (`ead12c51633fa1e00ca8a048203da2439feb950e`, MIT)
- 원본 README 원문: [`README.upstream.md`](README.upstream.md)
- Logent 변경 내역: [`NOTICE`](NOTICE), [`docs/insane-search.md`](docs/insane-search.md)
- 플러그인 id: `com.sleepysoong.logent.insane-search`
- 플러그인 키: `sleepysoong:insane_search` (`logent-plugin.json` 단일 정의)
- 필수 참조: `sleepysoong:browser_use` · Logent 0.0.84 이상 · API artifact 4.0.0

## 무엇을 하나요

공개 페이지가 HTTP·403·자바스크립트 셸로 읽히지 않으면 Phase 0→3의 HTTP 경로로
본문을 다시 읽어요. 로그인·CAPTCHA·보안 모듈·차단을 우회하지 않아요.
HTTP 수집이 끝나도 브라우저 확인이 필요하면 `needs_browser: true`와
`untried_routes: ["browser_use"]`를 돌려줘요. 모델이 정식 `browser_use`를 호출하며,
이 플러그인은 로컬 Playwright·Puppeteer·nodriver·patchright를 설치하거나 실행하지 않아요.
`--no-playwright`는 HTTP-only 호환 옵션이고 생략해도 동작이 같아요.

## 구조

```text
skills/insane-search/   원본 엔진·스킬·참조 (upstream 경로 그대로)
plugin/                 Logent Kotlin 플러그인과 자산 패키징
tests/python/           Logent가 추가한 안전 회귀 테스트
scripts/                검증·서명 .lpg·릴리스
```

엔진은 `skills/insane-search/engine` 한 곳만 원천으로 써요. 별도 복사본을 두지 않아
upstream을 합칠 때 충돌이 줄어요. `plugin/build.gradle.kts`가 실행에 필요한 파일만
`engine.zip`으로 묶고, `plugin/src/main/assets/`는 빌드 산출물이라 저장소에 넣지 않아요.

공개 의존성은 `sleepysoong:browser_use`이며 manifest의 가용성 판단에만 사용해요.
다른 플러그인의 준비 기능이나 데스크톱을 자동으로 시작하지 않아요.
`ensureReady`는 Termux Python을 유지하면서 필요한 라이브러리만 설치해요.
Android Python 3.14/ARM64에서는 `curl_cffi>=0.17.0`과 `cffi>=2.1.1`을 사용하고,
CFFI 소스 빌드를 위해 Termux `pkg`의 `clang`, `pkg-config`, `libffi`가 필요해요.
배포 표식이 같아도 import를 먼저 확인하며, 예전 ABI나 누락된 의존성을 재설치해요.

## 검증과 빌드

Android SDK 37, JDK 21, Python 3.11 이상이 필요해요. API artifact 4.0.0은
`plugin-api.lock`에 고정하며 GitHub Packages 읽기 권한이 있는 `GITHUB_ACTOR`와
`GITHUB_TOKEN`을 환경에서 받아요.

```bash
./scripts/test.sh --python-only
./scripts/test.sh
LOGENT_CONTENT_SIGNING_KEY_FILE="$HOME/.local/share/logent/content-signing.pem" \
  ./scripts/build.sh
# build/dist/logent-insane-search-v<VERSION>.lpg
```

서명 개인키는 저장소 밖에만 두고, APK에 고정된 ECDSA P-256 공개키와 맞는 패키지만
설치돼요.

## upstream 업데이트

```bash
git fetch upstream
git switch logent
git merge upstream/main
./scripts/test.sh
git push origin logent
```

합친 뒤 원본 커밋을 `UPSTREAM_COMMIT`에 갱신하고, Logent 패치(`phase0.py`의 공용 주소
검사)가 유지됐는지 확인해요. upstream의 Claude Code 설치 스크립트·마켓플레이스 파일은
Logent `.lpg`에 넣지 않아요.

## 라이선스

원본 엔진·스킬은 MIT이며 루트 `LICENSE`와 `DISCLAIMER.md`를 그대로 보존해요.
`plugin/`의 Logent Kotlin 통합 코드는 GPL-3.0(`plugin/LICENSE`)이에요.
