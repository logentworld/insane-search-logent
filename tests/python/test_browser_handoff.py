"""기존 플러그인 테스트 진입점에서 원본 엔진의 행동 회귀를 함께 실행해요."""
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "insane-search"))


def load_tests(loader, tests, pattern):
    for name in ("test_t7_browser_gate", "test_cli_result"):
        module = importlib.import_module(f"engine.tests.{name}")
        tests.addTests(loader.loadTestsFromModule(module))
    return tests


if __name__ == "__main__":
    unittest.main()
