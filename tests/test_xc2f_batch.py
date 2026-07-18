from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import xc2f_batch


def completed(command: list[str], returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout="", stderr="")


def test_run_both_stops_before_transpile_when_c_build_fails(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_run(command, *, action, label):
        calls.append((action, label))
        return completed(command, returncode=1), 0.01

    monkeypatch.setattr(xc2f_batch, "_run_command", fake_run)

    ok, rc, outcome = xc2f_batch._run_both_pipeline(
        c_file=tmp_path / "bad.c",
        fortran_source=tmp_path / "bad.f90",
        xc2f_path=tmp_path / "xc2f.py",
        transpile_flags=[],
        run_diff=False,
        time_both=False,
    )

    assert (ok, rc, outcome) == (False, 1, "original_c_build_fail")
    assert calls == [("Build", "original-c")]


def test_run_both_builds_everything_before_running(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    fortran_source = tmp_path / "hello.f90"

    def fake_run(command, *, action, label):
        calls.append((action, label))
        if label == "c-to-fortran":
            fortran_source.write_text("program main\nend program main\n", encoding="utf-8")
        return completed(command), 0.01

    monkeypatch.setattr(xc2f_batch, "_run_command", fake_run)

    ok, rc, outcome = xc2f_batch._run_both_pipeline(
        c_file=tmp_path / "hello.c",
        fortran_source=fortran_source,
        xc2f_path=tmp_path / "xc2f.py",
        transpile_flags=[],
        run_diff=False,
        time_both=False,
    )

    assert (ok, rc, outcome) == (True, 0, "full_pass")
    assert calls == [
        ("Build", "original-c"),
        ("Transpile", "c-to-fortran"),
        ("Build", "transformed-fortran"),
        ("Run", "original-c"),
        ("Run", "transformed-fortran"),
    ]


def test_run_both_batch_continues_after_a_failed_file(tmp_path, monkeypatch) -> None:
    sources = [tmp_path / "first.c", tmp_path / "second.c"]
    for source in sources:
        source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    processed: list[Path] = []

    def fake_pipeline(**kwargs):
        processed.append(kwargs["c_file"])
        return False, 1, "original_c_build_fail"

    monkeypatch.setattr(xc2f_batch, "_expand_inputs", lambda inputs: sources)
    monkeypatch.setattr(xc2f_batch, "_run_both_pipeline", fake_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xc2f_batch.py",
            "*.c",
            "--run-both",
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert xc2f_batch.main() == 1
    assert processed == sources
