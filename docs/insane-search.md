# insane-search 통합

Logent는 공개 웹 페이지가 WAF·403·자바스크립트 셸로 막혔을 때
[fivetaku/insane-search](https://github.com/fivetaku/insane-search) v0.17.4 엔진을 사용해 다시 읽어요.
원본 커밋은 `ead12c51633fa1e00ca8a048203da2439feb950e`, 라이선스는 MIT예요.

## 구성

- 원본 엔진: `insane-search/engine`, MIT 라이선스(`insane-search/LICENSE`)
- 원본 참조·테스트: `insane-search/references`, `insane-search/tests`, `insane-search/engine/tests`
- 고정 버전: `insane-search/UPSTREAM_COMMIT`, `TermuxScripts.INSANE_VERSION`
- APK 자산: Gradle `insaneSearchZip`이 실행에 필요한 엔진만 `insane-search.zip`으로 묶어요.
  참조·테스트·`__pycache__`·관찰 기록은 ZIP에서 제외해요.
- Termux 배포: `~/.logent/insane-search/`에 풀고 `VERSION` 파일로 재배포를 판단해요.
  임시 디렉터리에서 ZIP을 검증·추출한 뒤 `engine/`을 교체하고, 의존성 import와
  `curl_cffi>=0.15.0`을 확인한 뒤에만 `VERSION`을 써요.
- 실행: `python3 -m engine <URL> --json-content --no-playwright --device auto --timeout 20 --max-attempts 24`
- 지원: Phase 0(Reddit·X·YouTube·Threads), probe, TLS 지문 격자, 추출·PDF·JSON-LD,
  markdown, 학습·재시도, 실패 게이트. Playwright 로컬 폴백은 보안·의존성 때문에 꺼요.
- 의존성: `curl_cffi>=0.15.0`, `beautifulsoup4`, `pyyaml`, `pypdf`, `markdownify`, `yt-dlp`

## 호출 순서

1. 앱이 직접 HTTP로 페이지를 읽어요.
2. 챌린지·빈 셸·짧은 본문이면 insane-search를 불러요. 셸 제한은 최대 540초예요.
3. insane-search도 실패하면 Jina Reader로 넘어가요.
4. 실패한 페이지도 본문이 있으면 `insane-search(미확인)` 레이어와
   `untried_routes`·`needsBrowser`·verdict 메모를 함께 전달해요.
5. 모든 본문은 `<untrusted_web>` 경계 안에서만 모델에 전달하고, 본문이 경계 태그를
   위조해도 무력화하며 잘라도 닫는 태그를 보존해요.

`web_search`와 `web_research`는 Brave Search API 키가 있으면 Brave를 먼저 쓰고,
없거나 실패하면 DuckDuckGo·Jina·Bing으로 폴백해요. insane-search 엔진은 Brave 키를 쓰지 않아요.

## 보안

- Phase 0 호스트 판정은 정확한 호스트/서브도메인만 인정해 `reddit.com.evil.com` 같은 위장을 거부해요.
- Phase 0 리다이렉트는 홉마다 `safety.classify_url`로 공용 주소인지 확인해요.
- 앱의 직접 HTTP와 insane-search 모두 공용 HTTPS만 허용하고, 리다이렉트마다 같은 검사를 해요.
- refs 수집은 HTTPS만 허용하고, Playwright 폴백을 끈 채로 실행해요.
- `deep_research`의 원문 스냅샷은 `~/.logent/insane-search` 엔진을 사용하고 Playwright를 끄며,
  검증 게이트의 문자열 대조에만 쓰고 모델 컨텍스트에 원문을 직접 넣지 않아요.

## 키 보관

- 앱 설정에 입력한 Brave 키는 앱 전용 SharedPreferences에만 저장해요.
- Termux에서는 `~/.logent/brave.key`(0600)를 읽기 전용 대안으로 써요.
- insane-search는 `BRAVE_SEARCH_API_KEY`를 읽지 않으므로 엔진 명령에 키를 넘기지 않아요.
- 키는 저장소·APK·로그에 넣지 않아요.

## 제한

- 로그인·유료 장벽은 우회하지 않고 `authentication required`로 끝내요.
- Playwright 폴백은 앱에서 끄고, 필요하면 `browser_use`(Chromium CDP)로 직접 열어요.
- Termux에 Python이 없거나 의존성 설치가 실패하면 직접 HTTP·Jina 경로만 동작해요.
- 실제 기기의 WAF 사이트에서 전체 Phase 0→3를 검증한 것은 아니에요. 엔진 소스·Phase 0 보안·
  경계 이스케이프·배포 실패 처리를 테스트했고, live 사이트 스모크는 사용자가 요청할 때 확인해요.

원본 변경 내역은 [`LOGENT-NOTICE.md`](../insane-search/LOGENT-NOTICE.md)에 있어요.
