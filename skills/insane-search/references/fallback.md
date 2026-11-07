# HTTP 수집 실패와 browser_use 인계

엔진은 공개 HTTP Phase 0~3 수집 경로를 유지해요. 브라우저 렌더링은 엔진 내부 실행이 아니라 모델의 공식 `sleepysoong:browser_use` 호출로 분리해요.

## 단일 진입점으로 수집해요

```bash
python3 -m engine "https://example.com/article" --json-content
```

- Phase 0에서는 플랫폼의 공개 API·피드·미디어 경로를 먼저 사용해요.
- 이후 HTTP probe와 검증, 프로파일 감지, URL·TLS·referer 후보 수집을 진행해요.
- 각 응답의 상태·본문·챌린지 신호·성공 셀렉터를 검증해요. 첫 HTTP 200만으로 성공을 선언하지 않아요.
- JSON의 `trace`, `summary`, `stop_reason`을 같은 실행에서 읽어요. 진단 형식만 바꾸기 위해 재수집하지 않아요.

## 결과를 구분해요

| 결과 | 계약 | 다음 행동 |
|------|------|-----------|
| HTTP 수집 성공 | `ok=true`, `needs_browser=false`, `untried_routes=[]`예요. | 외부 데이터 경계를 유지해서 본문을 사용해요. |
| 브라우저가 필요한 HTTP 실패 | `ok=false`, `needs_browser=true`, `untried_routes=["browser_use"]`예요. | 모델이 공식 `browser_use`를 호출해요. |
| 인증 필요나 없는 문서 | `ok=false`, `needs_browser=false`, `untried_routes=[]`예요. | 수집 한계를 알려요. |

공개 403·전송 예외·빈 본문·HTTP 오류를 성공으로 승격하지 않아요. 제목·OGP·JSON-LD만 얻었다면 본문 전체를 읽었다고 말하지 않아요. 429는 과도하게 재요청하지 않아요.

## 외부 브라우저를 호출해요

모델이 공식 `sleepysoong:browser_use`의 `browser_use`에 원래 공개 URL과 필요한 내용을 전달해요. 실제 도구 스키마에 맞게 호출하고, 반환한 본문과 출처 URL을 확인해요. HTTP 실패 결과와 외부 브라우저 결과를 구분해요.

로컬 브라우저 실행기·템플릿·쿠키 브리지·렌더 병합은 사용하지 않아요. Node·Chrome·Playwright나 MCP 서버를 설치하지 않아요. `--no-playwright`의 유무와 `enable_playwright=True`는 이 경계를 바꾸지 않아요.

## 보안 경계에서 중단해요

로그인·페이월·CAPTCHA·보안 확인·접근 차단을 우회하지 않아요. 403 인계가 있더라도 브라우저에 보안 경계가 나타나면 중단하고 알려요. 쿠키나 자격 증명을 옮겨 재요청하지 않아요. 공식 도구를 쓸 수 없거나 모든 허용 경로에서 실패했다면 시도 이력과 한계를 그대로 보고해요.

상세 호출 기준은 [playwright.md](playwright.md), HTTP 프로파일은 [tls-impersonate.md](tls-impersonate.md), 보조 메타데이터는 [metadata.md](metadata.md)를 참고해요.
