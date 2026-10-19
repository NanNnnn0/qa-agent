"""Fixed pytest template for one pinned API run batch.

The executor copies this file into a temporary directory and passes the run
context through ``QA_RUN_CONTEXT``. Results are appended to ``QA_RUN_RESULT``
after every case, so a crash keeps the cases that already ran. Do not edit this
file per project: project variation belongs in the case data.
"""

from __future__ import annotations

import json
import os

import pytest

from nanobot.qa.runner import CaseRunner

_CONTEXT_PATH = os.environ["QA_RUN_CONTEXT"]
_RESULT_PATH = os.environ["QA_RUN_RESULT"]

with open(_CONTEXT_PATH, encoding="utf-8") as handle:
    CONTEXT = json.load(handle)

CASES = CONTEXT["cases"]
RESULTS: list[dict] = []
_RUN_VARIABLES: dict[str, str] = {}


def _write_results() -> None:
    with open(_RESULT_PATH, "w", encoding="utf-8") as handle:
        json.dump(RESULTS, handle, ensure_ascii=False)


def _runner() -> CaseRunner:
    return CaseRunner(CONTEXT["base_url"], default_headers=CONTEXT.get("headers") or {})


@pytest.mark.parametrize("case", CASES, ids=[case["code"] for case in CASES])
def test_case(case: dict) -> None:
    variables = dict(CONTEXT.get("variables") or {})
    variables.update(
        {f"run.{key}": str(value) for key, value in _RUN_VARIABLES.items()}
    )
    extract = (case.get("api") or {}).get("extract") or {}
    result = _runner().run_case(case, variables, extract=extract)
    for key, value in (result.get("extracted") or {}).items():
        _RUN_VARIABLES[key] = value
    RESULTS.append(result)
    _write_results()
    if result["status"] != "passed":
        pytest.fail(
            f"{case['code']}: {result.get('message') or result['status']}",
            pytrace=False,
        )
