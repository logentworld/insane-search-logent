# insane-search 통합

[fivetaku/insane-search](https://github.com/fivetaku/insane-search) v0.17.4 엔진을
Logent의 `PageRescueService`로 제공해요. 원본 커밋은
`ead12c51633fa1e00ca8a048203da2439feb950e`이고 MIT 고지를 유지해요.

## 실행과 배포

- 단일 원천은 `skills/insane-search/engine`이에요. 별도 엔진 사본을 만들지 않아요.
- `plugin/build.gradle.kts`의 `insaneSearchEngineZip`이 `engine.zip`을 만들고,
  APK의 `assets/plugins/insane-search/engine.zip`에 넣어요.
- 테스트·브라우저 템플릿·Node 패키지·캐시를 실행 ZIP에서 제외해요.
- Termux 배포 위치는 `~/.logent/plugins/insane-search/`예요.
- `EngineRuntime.ENGINE_VERSION`은 upstream 커밋과 별도의 Logent 배포 revision을
  포함해요. `CONTENT`는 콘텐츠 아카이브 경로와 호스트 버전의 식별자예요.
  같은 upstream 커밋이어도 Logent 엔진 수정은 새 배포 revision으로 교체해요.
- `ensureReady`는 `VERSION`·`CONTENT` fast path보다 먼저 의존성을 import해요.
  누락·기존 ABI 실패가 있으면 필요한 라이브러리를 업그레이드·재설치하고 새 Python
  프로세스에서 import를 검증해요. 이후 자산을 staging·검증·원자 교체하고 표식을 써요.
- 의존성은 `curl_cffi>=0.17.0`, `beautifulsoup4`, `pyyaml`, `pypdf`, `markdownify`,
  `yt-dlp`예요. Android는 `cffi>=2.1.1`을 소스 빌드하며 Termux `pkg`의 `clang`,
  `pkg-config`, `libffi`가 필요해요. 빌드용 `setuptools`, `wheel`, `pycparser`도 준비해요.
- Python·pip 자체는 업그레이드하지 않아요. 설치 실패 출력은 마지막 진단으로 길이를
  제한하고 환경의 키·토큰과 URL을 가려요. 실패한 준비는 성공으로 캐시하지 않아요.
- CPython/Linux에서는 Android 소스 빌드 전제 없이 일반 pip 라이브러리 설치를 사용해요.
- API artifact는 `com.sleepysoong.logent`의 4.0.0 계약을 유지해요.

## HTTP-only와 browser_use 계약

```sh
python3 -m engine 'https://example.com/' --json-content --no-playwright \
  --device auto --timeout 20 --max-attempts 24
```

Phase 0 공식·공개 경로, HTTP probe·격자·추출·PDF·JSON-LD·markdown은 유지해요.
`--no-playwright`를 생략해도 로컬 브라우저는 실행하지 않아요. Python 호출의 기존
`enable_playwright`·`max_browser_attempts` 인자는 HTTP-only 호환 인자로만 받아요.
Playwright·Puppeteer·nodriver·patchright 설치나 실행 경로는 제공하지 않아요.

HTTP 수집이 성공하면 `ok: true`, `needs_browser: false`와 본문을 돌려줘요.
HTTP 실패·예외·빈 본문은 성공으로 승격하지 않아요. 브라우저 확인이 필요한 실패는
다음 필드로 모델에 넘겨요. `stop_reason`과 `summary`에는 실제 중단 사유와 다음
행동을 한글 해요체로 설명해요.

```json
{
  "ok": false,
  "needs_browser": true,
  "untried_routes": ["browser_use"],
  "stop_reason": "HTTP 경로로 읽지 못했어요.",
  "summary": "정식 browser_use로 공개 페이지를 확인해 주세요."
}
```

Kotlin은 `needs_browser`를 `WebRescue.needsBrowser`로, `untried_routes`를
`untriedRoutes`로 전달하고 실패 진단에는 `stop_reason`·`summary`를 보존해요.
본문은 프로세스 정상 종료·`ok: true`·비어 있지 않은 출력이 모두 확인된 경우에만
반환해요. 실패 결과의 빈 원문 경계나 차단 응답을 수집 성공으로 표시하지 않아요.
실제 외부 브라우저 fallback은 모델의 정식 `browser_use` 호출로 완료해요.
로그인·CAPTCHA·보안 모듈·차단을 우회하지 않으며 인증 필요·404는 브라우저 재시도를
강요하지 않아요. MCP 명령이나 로컬 브라우저 설치를 요구하지 않아요.

공개 플러그인 의존성은 `sleepysoong:browser_use`예요. dependency는 manifest의
가용성 gating일 뿐이고, 다른 플러그인의 일반 준비나 X11 시작을 자동 실행하지 않아요.

## 안전 경계

- Phase 0 호스트 판정은 정확한 호스트/서브도메인만 인정해 위장 호스트를 거부해요.
- Phase 0 리다이렉트는 홉마다 `safety.classify_url`로 공용 주소인지 검사해요.
- 웹 본문은 신뢰하지 않는 데이터이며 원본 `<untrusted_web>` 경계를 유지해요.
- 엔진에는 Brave 키를 전달하지 않고 XAI 경로를 끈 채 실행해요.
- upstream 라이선스·이력·고지는 그대로 보존해요. 변경 목록은 [`NOTICE`](../NOTICE)에 있어요.

## 통합 후 검증

`./scripts/test.sh`의 Python 17개·JVM 10개 회귀와 Android lint·빌드를
실행했어요. 실제 Termux Android Python 3.14/ARM64에서 `ensureReady`를 거쳐
`example.com`의 HTTP 본문을 읽었어요. 이어 코어 `web_fetch` → 실제
`PageRescueService` → Termux 엔진 경로로 공개 HTTP 403을 조회했어요.
실패 본문은 비었고 `needsBrowser=true`·`untriedRoutes=[browser_use]`를
유지했으며, 최종 `web_fetch`도 오류와 브라우저 인계 진단을 표시했어요.

공개 URL의 응답 정책은 바뀔 수 있으므로 회귀 스모크에는 실제 403을 돌려주는
주소를 사용해요. 모델의 후속 도구 선택은 자동 검증하지 않았으며, 앱 설치·실제
Activity 조작을 이 결과로 주장하지 않아요.
