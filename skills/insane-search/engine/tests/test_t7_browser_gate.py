#!/usr/bin/env python3
"""HTTP 수집과 모델 browser_use 인계의 실제 결과를 검증해요."""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine import __main__ as cli
from engine import fetch_chain as fc
from engine import observations_log, phase0, safety, transport

URL = "https://public.example/article"
ARTICLE = "<html><body><article>" + "공개 기사 본문을 읽을 수 있어요. " * 400 + "</article></body></html>"


def response(status=200, text=ARTICLE):
    return SimpleNamespace(status_code=status, text=text, content=text.encode(), url=URL,
                           headers={"content-type": "text/html"},
                           cookies=SimpleNamespace(jar=[]))


@contextmanager
def http_only(reply=None, error=None, phase0_result=None):
    """전송 경계만 대체하고 예외 처리와 검증, CLI 직렬화는 그대로 사용해요."""
    session = Mock()
    if error is not None:
        session.get.side_effect = error
    else:
        session.get.return_value = reply
    entry = SimpleNamespace(session=session, injected_ua=None, requests_made=0)
    candidate = SimpleNamespace(profile_id="generic", transform="original", url=URL,
                                impersonate="chrome", referer="none", known_bad_sizes=None)
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            "INSANE_LEARN": "0", "INSANE_JITTER_MS_MIN": "0", "INSANE_JITTER_MS_MAX": "0",
        }))
        stack.enter_context(patch.object(safety, "classify_url", return_value=(True, "")))
        stack.enter_context(patch.object(transport, "pool_enabled", return_value=False))
        stack.enter_context(patch.object(transport, "available_impersonates", return_value=None))
        stack.enter_context(patch.object(transport.POOL, "get", return_value=entry))
        stack.enter_context(patch.object(fc, "_load_profiles", return_value={}))
        stack.enter_context(patch.object(fc, "last_load_error", return_value=None))
        stack.enter_context(patch.object(fc, "detect", return_value=[]))
        stack.enter_context(patch.object(fc, "_build_plan", return_value=[candidate]))
        stack.enter_context(patch.object(phase0, "route", return_value=phase0_result))
        stack.enter_context(patch.object(observations_log, "log_fetch"))
        launch = stack.enter_context(patch("subprocess.Popen"))
        yield session, launch
        launch.assert_not_called()


class BrowserHandoffTests(unittest.TestCase):
    def assert_handoff(self, result):
        self.assertFalse(result.ok)
        self.assertTrue(result.needs_browser)
        self.assertEqual(result.untried_routes, ["browser_use"])
        payload = result.to_dict()
        self.assertIs(payload["needs_browser"], True)
        self.assertNotIn("must_invoke_playwright_mcp", payload)
        self.assertTrue(result.trace)
        self.assertTrue(all(attempt.executor == "curl_cffi" for attempt in result.trace))

    def test_http_success_does_not_request_browser(self):
        with http_only(response()) as (session, _):
            result = fc.fetch(URL, success_selectors=["article"], enable_markdown=False)
        self.assertTrue(result.ok)
        self.assertFalse(result.needs_browser)
        self.assertEqual(result.untried_routes, [])
        self.assertEqual(result.content, ARTICLE)
        session.get.assert_called_once()

    def test_public_403_hands_off_without_launching_browser(self):
        for options in ({}, {"enable_playwright": True}, {"enable_playwright": False}):
            with self.subTest(options=options), http_only(response(403)):
                result = fc.fetch(URL, **options)
            self.assert_handoff(result)
            self.assertEqual(result.trace[-1].status, 403)

    def test_public_403_runs_real_http_profile_plan_before_handoff(self):
        build_plan = fc._build_plan
        hit = SimpleNamespace(profile_id="unknown_challenge")
        with http_only(response(403)) as (session, _), \
                patch.object(fc, "_build_plan", build_plan), \
                patch.object(fc, "detect", return_value=[hit]):
            result = fc.fetch(URL, max_attempts=2)
        self.assert_handoff(result)
        self.assertEqual(result.trace[-1].status, 403)
        self.assertEqual(session.get.call_count, 2)

    def test_transport_exception_cannot_become_success(self):
        with http_only(error=RuntimeError("전송에 실패했어요.")):
            result = fc.fetch(URL)
        self.assert_handoff(result)
        self.assertEqual(result.content, "")
        self.assertTrue(all(attempt.error for attempt in result.trace))

    def test_empty_success_status_cannot_become_success(self):
        for text in ("", "   \n\t"):
            with self.subTest(text=text), http_only(response(200, text)):
                result = fc.fetch(URL)
            self.assert_handoff(result)

    def test_rich_error_body_cannot_become_success(self):
        for status in (429, 500, 503):
            with self.subTest(status=status), http_only(response(status)):
                result = fc.fetch(URL, enable_retry=False)
            self.assert_handoff(result)
            self.assertEqual(result.trace[-1].status, status)

    def test_http200_security_page_is_not_collected_content(self):
        text = "<html><body>Checking your browser. Verify you are human. CAPTCHA</body></html>"
        with http_only(response(200, text)):
            result = fc.fetch(URL)
        self.assert_handoff(result)
        self.assertNotIn(result.verdict, ("strong_ok", "weak_ok"))

    def test_authentication_and_missing_page_do_not_escalate(self):
        for status in (401, 404):
            with self.subTest(status=status), http_only(response(status)):
                result = fc.fetch(URL)
            self.assertFalse(result.ok)
            self.assertFalse(result.needs_browser)
            self.assertEqual(result.untried_routes, [])

    def test_phase0_success_remains_http_only(self):
        p0 = {"ok": True, "content": ARTICLE, "final_url": URL,
              "platform": "fixture", "route": "public_api",
              "attempts": [{"route": "public_api", "ok": True, "status": 200}]}
        with http_only(response(403), phase0_result=p0) as (session, _):
            result = fc.fetch(URL)
        self.assertTrue(result.ok)
        self.assertFalse(result.needs_browser)
        self.assertEqual(result.untried_routes, [])
        self.assertEqual(result.content, ARTICLE)
        session.get.assert_not_called()

    def test_phase0_exception_preserves_http_failure(self):
        with http_only(response(403)), patch.object(
                phase0, "route", side_effect=RuntimeError("공개 API에 실패했어요.")):
            result = fc.fetch(URL)
        self.assertFalse(result.ok)
        self.assertTrue(result.needs_browser)
        self.assertEqual(result.untried_routes, ["browser_use"])
        self.assertTrue(any(attempt.phase == "phase0" and attempt.error
                            for attempt in result.trace))

    def test_phase0_empty_or_http_error_cannot_become_success(self):
        for status, content in ((200, ""), (200, "  \n"), (403, ARTICLE)):
            p0 = {"ok": True, "content": content, "final_url": URL,
                  "platform": "fixture", "route": "public_api",
                  "attempts": [{"route": "public_api", "ok": True, "status": status}]}
            with self.subTest(status=status, content=bool(content)), http_only(
                    response(403), phase0_result=p0):
                result = fc.fetch(URL)
            self.assertFalse(result.ok)
            self.assertTrue(result.needs_browser)
            self.assertEqual(result.untried_routes, ["browser_use"])

    def test_cli_default_and_no_playwright_are_http_only(self):
        for flags in ([], ["--no-playwright"]):
            with self.subTest(flags=flags), http_only(response(403)):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli.main([URL, "--json-content", *flags])
            self.assertEqual(code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIs(payload["needs_browser"], True)
            self.assertEqual(payload["untried_routes"], ["browser_use"])
            self.assertNotIn("must_invoke_playwright_mcp", payload)
            self.assertIn("browser_use", stderr.getvalue())
            self.assertTrue(all(attempt["executor"] == "curl_cffi" for attempt in payload["trace"]))


if __name__ == "__main__":
    unittest.main()
