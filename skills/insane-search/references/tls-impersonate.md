# TLS 임퍼소네이션 — curl_cffi

> TLS 핑거프린트(JA3/JA4) 기반 WAF에 대응하는 핵심 방법.
> 일반 curl/requests는 OpenSSL 핑거프린트라 즉시 차단되지만,
> curl_cffi는 실제 브라우저(Chrome/Safari/Firefox)의 TLS 핑거프린트를 복제한다.

## 의존성

```bash
python3 -c "import curl_cffi" 2>/dev/null || pip install -U "curl_cffi>=0.15.0" -q
```

설치 후 사용 가능. **미설치를 이유로 이 스텝을 건너뛰지 않는다.**

## HTTP 엔진을 단일 진입점으로 사용해요

TLS 후보·referer·URL 변형과 응답 검증은 엔진에 맡겨요. HTTP 200이나 본문 길이만으로 성공을 판단하는 별도 클라이언트를 만들지 않아요.

```bash
python3 -m engine "https://example.com/article" --json-content
```

`ok=false`이고 `needs_browser=true`이면 모델이 공식 `sleepysoong:browser_use`의 `browser_use`를 호출해요. 예외·빈 본문·HTTP 오류를 성공으로 승격하지 않아요. 로그인·CAPTCHA·보안 확인·접근 차단은 우회하지 않아요.

## 임퍼소네이션 타겟 목록 (v0.15.0)

generic alias는 항상 최신 버전으로 해석된다. **2026년에 chrome99 같은 옛 버전은 WAF가 의심하므로 generic alias 사용 권장.**

| Alias | 해석 (2026.04) | 용도 |
|-------|---------------|------|
| `safari` | safari260 | **한국 사이트 최적** |
| `chrome` | chrome146 | 범용 (Cloudflare, Akamai) |
| `firefox` | firefox135 | chrome/safari 실패 시 대안 |
| `chrome_android` | chrome131_android | 모바일 API 엔드포인트 |
| `safari_ios` | safari260_ios | iOS 모바일 |

<details>
<summary>핀 버전 전체 (클릭)</summary>

```
chrome99, chrome100, chrome101, chrome104, chrome107, chrome110,
chrome116, chrome119, chrome120, chrome123, chrome124, chrome131,
chrome133a, chrome136, chrome142, chrome145, chrome146,
chrome131_android, edge99, edge101,
safari15_3, safari15_5, safari17_0, safari17_2_ios,
safari18_0, safari18_0_ios, safari260, safari260_ios,
firefox133, firefox135
```

</details>

## WAF별 최적 전략

WAF **제품**별 우선 시도 조합 — 특정 사이트가 아니라 제품 지문 기준 일반 가이드(No-Site-Name Rule).

| WAF | 최적 타겟 | 추가 조건 | 성공률 |
|-----|-----------|-----------|--------|
| F5 BIG-IP | `safari` | `Referer: <사이트 루트>` | ~70% |
| Cloudflare (TLS만) | `chrome` | Sec-Fetch-* 헤더 추가 | ~80% |
| Akamai | `chrome` | — | 80-90% |
| AWS WAF | `chrome` | — | ~80% |
| CloudFront | 불필요 | 일반 curl + Chrome UA로 충분 | 100% |

## 세션과 쿠키

```python
from curl_cffi import requests

# 세션 유지 (쿠키 자동 관리)
session = requests.Session(impersonate="safari")

# 첫 요청으로 세션 쿠키 획득
session.get("https://example.com/")

# 이후 요청에 쿠키 자동 전달
resp = session.get("https://example.com/search?q=...")
```

## 브라우저 쿠키를 전달하지 않아요

HTTP 세션의 일반 쿠키 관리는 유지하지만, 브라우저에서 얻은 인증·챌린지 쿠키를 엔진에 주입하지 않아요. 로컬 브라우저나 챌린지 해결 서비스를 설치하지 않아요. 렌더링이 필요한 공개 페이지는 모델이 공식 `browser_use`로 확인해요.

## 비동기 (async)

```python
import asyncio
from curl_cffi.requests import AsyncSession

async def fetch_many(urls):
    async with AsyncSession(impersonate="chrome") as session:
        tasks = [session.get(url) for url in urls]
        return await asyncio.gather(*tasks)
```

## HTTP/3 (v0.15.0+)

```python
from curl_cffi import requests
from curl_cffi.const import CurlHttpVersion

resp = requests.get(
    "https://www.cloudflare.com/",
    impersonate="chrome",
    http_version=CurlHttpVersion.V3,
)
```

WAF 벤더들이 아직 HTTP/3 핑거프린트를 적극 활용하지 않아 대응 효과가 높다.

## 대안 라이브러리

curl_cffi 실패 시 대안:

| 라이브러리 | 설치 | 특징 |
|-----------|------|------|
| primp | `pip install primp` | Rust 기반, Firefox 148까지, 고성능 |
| wreq/rnet | `pip install wreq` | Rust 기반, 100+ 디바이스 프로필 |
| tls-client2 | `pip install tls-client2` | Go 기반 포크, 동기만 |

```python
# primp 예시
import primp
client = primp.Client(impersonate="chrome_146")
resp = client.get("https://example.com")
```

## curl_cffi가 못 뚫는 것

| 방어 수단 | curl_cffi | 대응 |
|-----------|-----------|------|
| TLS/JA3 핑거프린트 | 대응 가능 | 핵심 기능 |
| HTTP/2 SETTINGS 핑거프린트 | 대응 가능 | impersonate에 포함 |
| HTTP/3 QUIC 핑거프린트 | 대응 가능 (v0.15+) | 신규 |
| JS 챌린지 (Turnstile 등) | 처리하지 않아요. | 보안 확인을 우회하지 않고 중단해요. |
| CAPTCHA | 처리하지 않아요. | 풀이 서비스나 자동화를 사용하지 않아요. |
| IP 접근 차단 | 처리하지 않아요. | 프록시·VPN으로 우회하지 않아요. |
| 행동 기반 보안 확인 | 처리하지 않아요. | 우회 동작 없이 한계를 알려요. |

일반 공개 페이지의 렌더링이 필요하면 [browser_use 호출 안내](playwright.md)를 참고해요.
