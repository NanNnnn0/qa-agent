"""Tests for ``qa trace diff``: the git base side and the CI gate.

The fixture builds a real temporary git repository with a valid project, so the
base side is produced by ``git archive`` exactly as it is in CI.  Each test then
either commits a change (a second commit) or edits the worktree, which is what a
pull request looks like to ``diff``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from qa_trace.cli import main
from qa_trace.diff import DIFF_VERSION, compute_diff, render_diff

FIXTURES = Path(__file__).parent / "fixtures"
GIT = shutil.which("git")
PROJECT_IN_REPO = Path("qa-workbench") / "projects" / "demo"

pytestmark = pytest.mark.skipif(GIT is None, reason="git is required for the diff tests")

EXPECTED_KEYS = {
    "diff_version",
    "tool",
    "project",
    "base",
    "head",
    "tolerance",
    "regression",
    "exit_code",
    "reasons",
    "diagnostics",
    "counts",
    "coverage",
    "dangling",
    "orphan",
    "requirement_gaps",
    "needs_recheck",
}

COMPARISON_KEYS = {
    "base",
    "head",
    "comparable",
    "delta_percent",
    "worsening_points",
    "regression",
}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        [GIT or "git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


def _copy_project(source: Path, target: Path) -> Path:
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    return target


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "qa-trace@example.com")
    _git(root, "config", "user.name", "qa trace tests")
    _git(root, "config", "commit.gpgsign", "false")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def demo_repo(tmp_path: Path) -> tuple[Path, str]:
    """Return ``(repo_root, base_commit)`` for a repo holding one valid project."""
    root = tmp_path / "repo"
    root.mkdir()
    _copy_project(FIXTURES / "metrics_project", root / PROJECT_IN_REPO)
    _init_repo(root)
    return root, _commit(root, "base")


def _project(root: Path) -> Path:
    return root / PROJECT_IN_REPO


def _break_a_reference(project: Path) -> None:
    path = project / "testpoints" / "TP-LOGIN-001.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("- REQ-LOGIN-01", "- REQ-LOGIN-99"),
        encoding="utf-8",
    )


def _add_uncovered_requirement(project: Path) -> str:
    source = project / "sources" / "REQ-LOGIN-03.yaml"
    source.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "id: REQ-LOGIN-03",
                "type: req",
                "module: LOGIN",
                "title: 登录成功后跳转首页",
                "evidence:",
                "  - type: document",
                "    locator: docs/req/login-redirect.md#5.1",
                "    description: 需求文档 5.1 节：登录成功跳转",
                "    verified: external_unverified",
                "confidence: confirmed",
                "status: active",
                "owner: qa.zhang",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return "REQ-LOGIN-03"


def test_diff_without_changes_is_clean(demo_repo: tuple[Path, str]) -> None:
    root, base = demo_repo
    assert main(["trace", "diff", "--project", str(_project(root)), "--base", base]) == 0
    document = compute_diff(_project(root), base).to_dict()
    assert document["diff_version"] == DIFF_VERSION
    assert document["regression"] is False
    assert document["exit_code"] == 0
    assert document["reasons"] == []
    assert document["base"]["commit"] == base
    assert document["base"]["valid"] is True
    assert document["head"]["valid"] is True
    assert document["diagnostics"]["new"] == []
    assert document["diagnostics"]["resolved"] == []
    assert document["dangling"] == {"base": 0, "head": 0, "delta": 0, "new": False}
    assert document["orphan"]["added"] == []
    assert document["project"]["path_in_repo"] == PROJECT_IN_REPO.as_posix()
    for section, key in (
        ("requirement", "reviewed"),
        ("requirement", "current_valid"),
        ("behavior", "reviewed"),
        ("behavior", "current_valid"),
        ("automation", "reviewed"),
        ("orphan", "library"),
    ):
        comparison = document["coverage"][section][key]
        assert comparison["delta_percent"] == 0.0
        assert comparison["regression"] is False
        assert comparison["comparable"] is True


def test_diff_json_shape_is_stable(
    demo_repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = demo_repo
    code = main(
        ["trace", "diff", "--project", str(_project(root)), "--base", base, "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == EXPECTED_KEYS
    assert payload["tool"]["name"] == "qa_trace"
    assert payload["tolerance"] == {"coverage_points": 0.0, "source": "default"}
    assert set(payload["coverage"]) == {"requirement", "behavior", "automation", "orphan"}
    assert set(payload["coverage"]["requirement"]) == {"reviewed", "current_valid"}
    assert set(payload["coverage"]["automation"]) == {"reviewed"}
    assert set(payload["coverage"]["orphan"]) == {"library"}
    for section in payload["coverage"].values():
        for comparison in section.values():
            assert set(comparison) == COMPARISON_KEYS
            assert set(comparison["base"]) == {"numerator", "denominator", "percent"}
    assert set(payload["diagnostics"]) == {"new", "resolved", "unchanged_count", "counts"}
    assert set(payload["counts"]) == {"base", "head", "delta"}
    assert set(payload["orphan"]) == {"base", "head", "added", "removed", "counts"}
    assert set(payload["requirement_gaps"]) == {
        "base",
        "head",
        "new_uncovered_requirements",
        "resolved_uncovered_requirements",
        "new_cases_without_requirement_root",
        "resolved_cases_without_requirement_root",
    }
    assert set(payload["needs_recheck"]) == {"base", "head", "added", "removed"}
    # The temporary materialisation directory must never leak into the document.
    assert "qa-trace-diff-" not in json.dumps(payload)


def test_diff_reports_new_dangling_reference(
    demo_repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = demo_repo
    project = _project(root)
    _break_a_reference(project)
    _commit(root, "break the test point reference")

    code = main(
        ["trace", "diff", "--project", str(project), "--base", base, "--json"]
    )
    assert code == 1
    document = json.loads(capsys.readouterr().out)
    assert document["regression"] is True
    assert document["exit_code"] == 1
    codes = {reason["code"] for reason in document["reasons"]}
    assert {"new_errors", "new_dangling"} <= codes
    assert document["base"]["dangling_count"] == 0
    assert document["dangling"] == {"base": 0, "head": 1, "delta": 1, "new": True}
    new_codes = [item["code"] for item in document["diagnostics"]["new"]]
    assert "TRACE_REF_MISSING" in new_codes
    assert document["diagnostics"]["resolved"] == []
    # The worktree is only read: the committed breakage is what the head side sees.
    assert "REQ-LOGIN-99" in (
        project / "testpoints" / "TP-LOGIN-001.yaml"
    ).read_text(encoding="utf-8")
    assert "TRACE_REF_MISSING" in render_diff(
        compute_diff(project, base)
    )


def test_diff_reports_coverage_drop(
    demo_repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = demo_repo
    project = _project(root)
    new_source = _add_uncovered_requirement(project)
    _commit(root, "add a requirement without coverage")

    assert main(["trace", "diff", "--project", str(project), "--base", base]) == 1
    document = compute_diff(project, base).to_dict()
    assert {reason["code"] for reason in document["reasons"]} == {"coverage_drop"}
    requirement = document["coverage"]["requirement"]["reviewed"]
    assert requirement["base"]["percent"] == 50.0
    assert requirement["head"]["percent"] == 33.33
    assert requirement["delta_percent"] == -16.67
    assert requirement["worsening_points"] == 16.67
    assert requirement["regression"] is True
    assert document["requirement_gaps"]["new_uncovered_requirements"] == [new_source]
    new_errors = [
        item
        for item in document["diagnostics"]["new"]
        if item["severity"] == "error"
    ]
    assert new_errors == []
    # The base side is the committed tree, so it still knows two requirements.
    assert document["base"]["counts"]["sources"] == 5
    assert document["head"]["counts"]["sources"] == 6


def test_diff_tolerance_accepts_a_small_drop(demo_repo: tuple[Path, str]) -> None:
    root, base = demo_repo
    project = _project(root)
    _add_uncovered_requirement(project)

    tolerant = compute_diff(project, base, coverage_tolerance=20.0)
    assert tolerant.exit_code == 0
    assert tolerant.to_dict()["tolerance"] == {"coverage_points": 20.0, "source": "cli"}
    comparison = tolerant.to_dict()["coverage"]["requirement"]["reviewed"]
    assert comparison["regression"] is False
    assert comparison["worsening_points"] == 16.67

    strict = compute_diff(project, base, coverage_tolerance=10.0)
    assert strict.exit_code == 1
    assert {reason["code"] for reason in strict.to_dict()["reasons"]} == {"coverage_drop"}


def test_diff_reads_the_tolerance_from_project_config(
    demo_repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = demo_repo
    project = _project(root)
    _add_uncovered_requirement(project)
    project_yaml = project / "project.yaml"
    project_yaml.write_text(
        project_yaml.read_text(encoding="utf-8").replace(
            "  p0_ratio_max: 0.2", "  p0_ratio_max: 0.2\n  diff_coverage_tolerance: 25"
        ),
        encoding="utf-8",
    )

    document = compute_diff(project, base).to_dict()
    assert document["tolerance"] == {"coverage_points": 25.0, "source": "project"}
    assert document["regression"] is False

    # The CLI flag still wins over the project threshold.
    assert main(
        [
            "trace",
            "diff",
            "--project",
            str(project),
            "--base",
            base,
            "--coverage-tolerance",
            "1",
        ]
    ) == 1
    capsys.readouterr()


def test_diff_reports_resolved_diagnostics(demo_repo: tuple[Path, str]) -> None:
    root, base = demo_repo
    project = _project(root)
    _break_a_reference(project)
    broken_commit = _commit(root, "break the test point reference")

    # The broken commit is the base; the fix is committed as the head.
    path = project / "testpoints" / "TP-LOGIN-001.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("- REQ-LOGIN-99", "- REQ-LOGIN-01"),
        encoding="utf-8",
    )
    _commit(root, "fix the reference")

    document = compute_diff(project, broken_commit).to_dict()
    assert document["regression"] is False
    assert document["exit_code"] == 0
    assert [item["code"] for item in document["diagnostics"]["resolved"]] == [
        "TRACE_REF_MISSING",
        "TRACE_SOURCE_NO_DOWNSTREAM",
    ]
    assert document["diagnostics"]["new"] == []
    # A structurally broken base suppresses its metrics, so nothing is comparable.
    assert document["base"]["valid"] is False
    assert document["base"]["metrics_available"] is False
    assert document["base"]["metrics_suppressed"]
    comparison = document["coverage"]["requirement"]["reviewed"]
    assert comparison["comparable"] is False
    assert comparison["regression"] is False
    assert document["dangling"] == {"base": 1, "head": 0, "delta": -1, "new": False}


def test_diff_unknown_ref_exits_2(
    demo_repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root, _base = demo_repo
    assert main(
        ["trace", "diff", "--project", str(_project(root)), "--base", "no-such-ref"]
    ) == 2
    assert "TRACE_DIFF_BASE_UNKNOWN" in capsys.readouterr().out


def test_diff_outside_a_git_repository_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    standalone = _copy_project(FIXTURES / "metrics_project", tmp_path / "standalone")
    assert main(["trace", "diff", "--project", str(standalone), "--base", "HEAD"]) == 2
    assert "TRACE_DIFF_NOT_GIT" in capsys.readouterr().out


def test_diff_missing_project_exits_2(
    demo_repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = demo_repo
    assert main(
        ["trace", "diff", "--project", str(root / "nope"), "--base", base]
    ) == 2
    assert "TRACE_PROJECT_INVALID" in capsys.readouterr().out


def test_diff_project_absent_at_base_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "empty-repo"
    root.mkdir()
    _init_repo(root)
    _git(root, "commit", "--allow-empty", "-m", "empty base")
    base = _git(root, "rev-parse", "HEAD")
    project = _copy_project(FIXTURES / "metrics_project", root / PROJECT_IN_REPO)

    assert main(["trace", "diff", "--project", str(project), "--base", base]) == 2
    assert "TRACE_DIFF_BASE_MISSING" in capsys.readouterr().out


def test_diff_does_not_touch_the_worktree(
    demo_repo: tuple[Path, str],
    digest_tree: Callable[..., dict[str, str]],
) -> None:
    root, base = demo_repo
    project = _project(root)
    _add_uncovered_requirement(project)
    before = digest_tree(project)
    compute_diff(project, base)
    assert digest_tree(project) == before
