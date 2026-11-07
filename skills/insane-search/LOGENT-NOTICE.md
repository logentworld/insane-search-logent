# insane-search 출처와 Logent 변경

- 원본: https://github.com/fivetaku/insane-search
- 버전: v0.17.4
- 커밋: ead12c51633fa1e00ca8a048203da2439feb950e
- 라이선스: MIT (`LICENSE`), 원본 고지(`DISCLAIMER.md`)

## Logent에서 바꾼 것

- `engine/phase0.py`의 Reddit·YouTube 판정을 호스트 접미사 포함 검사에서 정확한 호스트/서브도메인 검사로 바꿨어요. `reddit.com.evil.com` 같은 위장 호스트가 Phase 0로 분류되지 않아요.
- `_cffi_get`이 리다이렉트를 자동으로 따라가지 않고, 홉마다 `safety.classify_url`로 공용 주소인지 확인한 뒤 다음 요청을 보내요. 사설·루프백·메타데이터 주소로의 리다이렉트는 요청 전에 거부해요.
- Logent의 `WebTools`가 페이지 본문·제목·URL의 `<untrusted_web>`/`</untrusted_web>`을 무력화하고, 본문을 잘라도 닫는 경계를 반드시 남겨요.
- `web_fetch`가 insane-search의 `verdict`·`untried_routes`·`needs_browser`를 진단 메모로 노출해요. HTTP 성공이면 `needs_browser=false`이고, 브라우저가 필요한 실패는 `needs_browser=true`, `untried_routes=["browser_use"]`예요.
- WAF 격자 시간을 고려해 `web_fetch`의 insane-search 셸 제한을 540초로 맞췄어요.
- Termux 배포는 임시 디렉터리에 풀어 `engine/`을 교체하고, `curl_cffi>=0.15.0`·`bs4`·`yaml`·`pypdf`·`markdownify`·`yt_dlp`를 실제 import로 확인한 뒤에만 `VERSION`을 기록해요. 손상 ZIP이나 의존성 실패는 `VERSION`을 남기지 않아요.
- 원본 이력과 라이선스는 유지하고, 로컬 브라우저 실행기·템플릿·쿠키 브리지·렌더 병합과 전용 테스트는 제거했어요. 회귀 테스트는 HTTP 함수·CLI 소비자 결과와 외부 인계 경계를 검증하도록 바꿨어요. APK의 실행 ZIP에는 엔진 실행에 필요한 파일만 넣어요.
- HTTP Phase 0~3 경로와 코어 API 4.0.0은 유지해요. `--no-playwright`는 HTTP-only 호환 스위치이고 옵션 생략이나 `enable_playwright=True`도 로컬 브라우저를 실행하지 않아요.
- 실제 브라우저 수집은 모델이 공식 `sleepysoong:browser_use`의 `browser_use`를 호출해요. 엔진은 브라우저나 MCP 서버를 설치하지 않아요. 로그인·CAPTCHA·보안 확인·접근 차단을 우회하지 않고, 예외·빈 본문·HTTP 오류를 성공으로 승격하지 않아요.

원본 라이선스와 저작권 고지는 `LICENSE`에 그대로 보존했어요.
