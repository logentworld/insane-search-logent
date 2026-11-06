import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2] / "skills" / "insane-search"
sys.path.insert(0, str(REPO))

from engine import phase0  # noqa: E402


class Phase0SafetyTest(unittest.TestCase):
    def test_detect_uses_exact_hosts_not_suffixes(self):
        self.assertIsNone(phase0._detect("https://reddit.com.evil.com/r/test"))
        self.assertIsNone(phase0._detect("https://youtube.com.evil.com/watch?v=1"))
        self.assertIsNone(phase0._detect("https://threads.net.evil.com/post/x"))
        self.assertEqual("reddit", phase0._detect("https://www.reddit.com/r/test"))
        self.assertEqual("youtube", phase0._detect("https://youtu.be/abc"))

    def test_cffi_get_rejects_private_redirect(self):
        calls = []

        class Response:
            def __init__(self, status, location=None):
                self.status_code = status
                self.headers = {"location": location} if location else {}

        class Requests:
            @staticmethod
            def get(url, **kwargs):
                calls.append(url)
                assert kwargs["allow_redirects"] is False
                return Response(302, "http://169.254.169.254/latest/meta-data")

        fake = types.ModuleType("curl_cffi")
        fake.requests = Requests
        with mock.patch.dict(sys.modules, {"curl_cffi": fake}):
            with self.assertRaisesRegex(ValueError, "unsafe redirect target"):
                phase0._cffi_get("https://reddit.com/r/test")
        self.assertEqual(["https://reddit.com/r/test"], calls)


if __name__ == "__main__":
    unittest.main()
