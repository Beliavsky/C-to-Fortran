#!/usr/bin/env python3
"""Batch runner for xc2f.py over explicit files, glob patterns, and @list files."""

from __future__ import annotations

import argparse
import glob
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from xc2f import DEFAULT_GFORTRAN_FLAGS


@dataclass
class CaseResult:
    source: str
    ok: bool
    rc: int
    status: str
    outcome: str
    fortran_source: str


def _has_glob_meta(s: str) -> bool:
    return any(ch in s for ch in "*?[]")


def _read_input_list(list_path: Path) -> List[str]:
    """Read one @list file, ignoring blank lines and comments."""
    try:
        text = list_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    out: List[str] = []
    for ln in text.splitlines():
        raw = ln.strip()
        if not raw or raw.startswith("#"):
            continue
        out.append(raw)
    return out


def _expand_inputs(items: List[str]) -> List[Path]:
    out: List[Path] = []
    seen = set()
    seen_lists = set()

    def add_input(it: str, *, base_dir: Path) -> None:
        if it.startswith("@"):
            list_path = Path(it[1:])
            if not list_path.is_absolute():
                list_path = base_dir / list_path
            try:
                list_key = str(list_path.resolve()).lower()
            except Exception:
                list_key = str(list_path).lower()
            if list_key in seen_lists:
                return
            seen_lists.add(list_key)
            for nested in _read_input_list(list_path):
                add_input(nested, base_dir=list_path.parent)
            return

        resolved = it
        p_in = Path(it)
        if not p_in.is_absolute():
            resolved = str(base_dir / p_in)

        matches: List[str]
        if _has_glob_meta(resolved):
            matches = glob.glob(resolved, recursive=True)
        else:
            matches = [resolved]

        for m in matches:
            p = Path(m)
            if p.is_dir():
                for q in sorted(p.rglob("*.c")):
                    k = str(q.resolve()).lower()
                    if k not in seen:
                        seen.add(k)
                        out.append(q)
                continue
            if p.suffix.lower() != ".c":
                continue
            if p.exists():
                k = str(p.resolve()).lower()
                if k not in seen:
                    seen.add(k)
                    out.append(p)

    for it in items:
        add_input(it, base_dir=Path.cwd())
    return sorted(out, key=lambda p: str(p).lower())


def _classify_outcome(ok: bool, stdout: str, stderr: str) -> str:
    txt = f"{stdout or ''}\n{stderr or ''}"
    if ok:
        return "full_pass"
    if "Transpile: FAIL" in txt:
        return "transpile_fail"
    if "Build (original-c): FAIL" in txt:
        return "original_c_build_fail"
    if "Build (transformed-fortran): FAIL" in txt:
        return "fortran_build_fail"
    if "Run (original-c): FAIL" in txt:
        return "original_c_run_fail"
    if "Run (transformed-fortran): FAIL" in txt:
        return "fortran_run_fail"
    return "other_fail"


def _show_process_output(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout and proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.stderr and proc.stderr.strip():
        print(proc.stderr.rstrip())


def _run_command(
    cmd: List[str],
    *,
    action: str,
    label: str,
) -> Tuple[Optional[subprocess.CompletedProcess[str]], float]:
    """Run and report one build/run command, including missing executables."""
    print(f"{action} ({label}): {' '.join(cmd)}")
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
        )
    except OSError as exc:
        elapsed = time.perf_counter() - started
        print(f"{action} ({label}): FAIL ({exc})")
        return None, elapsed
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        print(f"{action} ({label}): FAIL (exit {proc.returncode})")
        _show_process_output(proc)
    else:
        print(f"{action} ({label}): PASS")
        _show_process_output(proc)
    return proc, elapsed


def _run_both_pipeline(
    *,
    c_file: Path,
    fortran_source: Path,
    xc2f_path: Path,
    transpile_flags: List[str],
    run_diff: bool,
    time_both: bool,
) -> Tuple[bool, int, str]:
    """Build both languages before running either executable."""
    c_exe = fortran_source.with_name(f"{fortran_source.stem}.orig.exe")
    fortran_exe = fortran_source.with_suffix(".exe")

    c_build, _ = _run_command(
        ["gcc", str(c_file), "-lm", "-o", str(c_exe)],
        action="Build",
        label="original-c",
    )
    if c_build is None or c_build.returncode != 0:
        return False, c_build.returncode if c_build is not None else 1, "original_c_build_fail"

    # A failed transpilation must not leave an older output looking successful.
    if fortran_source.exists():
        fortran_source.unlink()
    transpile, _ = _run_command(
        [
            sys.executable,
            str(xc2f_path),
            str(c_file),
            "--out",
            str(fortran_source),
            *transpile_flags,
        ],
        action="Transpile",
        label="c-to-fortran",
    )
    if transpile is None or transpile.returncode != 0 or not fortran_source.is_file():
        if transpile is not None and transpile.returncode == 0 and not fortran_source.is_file():
            print("Transpile (c-to-fortran): FAIL (no Fortran source produced)")
        return False, transpile.returncode if transpile is not None and transpile.returncode else 1, "transpile_fail"

    fortran_build, _ = _run_command(
        [
            "gfortran",
            str(fortran_source),
            *DEFAULT_GFORTRAN_FLAGS,
            "-o",
            str(fortran_exe),
        ],
        action="Build",
        label="transformed-fortran",
    )
    if fortran_build is None or fortran_build.returncode != 0:
        return False, fortran_build.returncode if fortran_build is not None else 1, "fortran_build_fail"

    c_run, c_time = _run_command([str(c_exe)], action="Run", label="original-c")
    if c_run is None or c_run.returncode != 0:
        return False, c_run.returncode if c_run is not None else 1, "original_c_run_fail"

    fortran_run, fortran_time = _run_command(
        [str(fortran_exe)], action="Run", label="transformed-fortran"
    )
    if fortran_run is None or fortran_run.returncode != 0:
        return False, fortran_run.returncode if fortran_run is not None else 1, "fortran_run_fail"

    if run_diff:
        matches = (c_run.stdout == fortran_run.stdout) and (c_run.stderr == fortran_run.stderr)
        print(f"Run diff: {'MATCH' if matches else 'DIFF'}")
    if time_both and c_time > 0:
        print(f"Time ratio (fortran/c): {fortran_time / c_time:.3f}")
    return True, 0, "full_pass"


def main() -> int:
    t0 = time.perf_counter()
    ap = argparse.ArgumentParser(
        description="Run xc2f.py on multiple C files/directories/globs/@list files."
    )
    ap.add_argument("inputs", nargs="+", help="C files, directories, glob patterns, and/or @list files.")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("xc2f_batch_out"),
        help="Directory where generated Fortran files are written.",
    )
    ap.add_argument("--raw", action="store_true", help="Forward --raw to xc2f.py.")
    ap.add_argument("--refactor", action="store_true", help="Forward --refactor to xc2f.py.")
    ap.add_argument("--array", action="store_true", help="Forward --array to xc2f.py.")
    ap.add_argument("--array-inline", action="store_true", help="Forward --array-inline to xc2f.py.")
    ap.add_argument("--inline-temp", action="store_true", help="Forward --inline-temp to xc2f.py.")
    ap.add_argument("--tee", action="store_true", help="Forward --tee to xc2f.py.")
    ap.add_argument("--tee-orig", action="store_true", help="Forward --tee-orig to xc2f.py.")
    ap.add_argument("--tee-both", action="store_true", help="Forward --tee-both to xc2f.py.")
    ap.add_argument(
        "--run-both",
        action="store_true",
        help="Per-file pipeline: build C, transpile/build Fortran, then run both.",
    )
    ap.add_argument("--compile-both", action="store_true", help="Forward --compile-both to xc2f.py.")
    ap.add_argument("--compile-both-c", action="store_true", help="Forward --compile-both-c to xc2f.py.")
    ap.add_argument("--compile-c", action="store_true", help="Forward --compile-c to xc2f.py.")
    ap.add_argument("--run-diff", action="store_true", help="Forward --run-diff to xc2f.py.")
    ap.add_argument("--time-both", action="store_true", help="Forward --time-both to xc2f.py.")
    ap.add_argument("--limit", type=int, default=0, help="Process at most this many matched files (0 = no limit).")
    ap.add_argument("--maxfail", type=int, default=0, help="Stop after this many failures (0 = no limit).")
    ap.add_argument("--verbose", action="store_true", help="Print full xc2f output for PASS cases too.")
    ap.add_argument("--terse", action="store_true", help="Show only failing cases plus final totals.")
    args = ap.parse_args()

    if args.limit < 0:
        print("Invalid options: --limit must be >= 0.")
        return 1
    if args.maxfail < 0:
        print("Invalid options: --maxfail must be >= 0.")
        return 1
    if args.run_diff or args.time_both:
        args.run_both = True

    mode_flags = [args.run_both, args.compile_both, args.compile_both_c, args.compile_c]
    if sum(1 for flag in mode_flags if flag) > 1:
        print("Invalid options: choose at most one of --run-both, --compile-both, --compile-both-c, or --compile-c.")
        return 1
    if not any(mode_flags):
        args.compile_both = True

    c_files = _expand_inputs(args.inputs)
    if not c_files:
        print("No C files matched the provided inputs.")
        return 1
    if args.limit > 0:
        c_files = c_files[: args.limit]

    xc2f_path = Path(__file__).with_name("xc2f.py")
    if not xc2f_path.exists():
        print(f"Missing script: {xc2f_path}")
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results: List[CaseResult] = []
    failures = 0
    total = len(c_files)

    for i, cf in enumerate(c_files, start=1):
        rel = str(cf)
        out_path = args.out_dir / f"{i:04d}_{cf.stem}.f90"
        cmd = [sys.executable, str(xc2f_path), rel, "--out", str(out_path)]
        transpile_flags: List[str] = []
        if args.raw:
            cmd.append("--raw")
            transpile_flags.append("--raw")
        if args.refactor:
            cmd.append("--refactor")
            transpile_flags.append("--refactor")
        if args.array:
            cmd.append("--array")
            transpile_flags.append("--array")
        if args.array_inline:
            cmd.append("--array-inline")
            transpile_flags.append("--array-inline")
        if args.inline_temp:
            cmd.append("--inline-temp")
            transpile_flags.append("--inline-temp")
        if args.tee:
            cmd.append("--tee")
            transpile_flags.append("--tee")
        if args.tee_orig:
            cmd.append("--tee-orig")
            transpile_flags.append("--tee-orig")
        if args.tee_both:
            cmd.append("--tee-both")
            transpile_flags.append("--tee-both")
        if args.run_both:
            cmd.append("--run-both")
        elif args.compile_both:
            cmd.append("--compile-both")
        elif args.compile_both_c:
            cmd.append("--compile-both-c")
        elif args.compile_c:
            cmd.append("--compile-c")
        if args.run_diff:
            cmd.append("--run-diff")
        if args.time_both:
            cmd.append("--time-both")

        if not args.terse:
            print(f"[{i}/{total}] {rel}")
        if args.run_both:
            ok, rc, outcome = _run_both_pipeline(
                c_file=cf,
                fortran_source=out_path,
                xc2f_path=xc2f_path,
                transpile_flags=transpile_flags,
                run_diff=args.run_diff,
                time_both=args.time_both,
            )
            status = "PASS" if ok else "FAIL"
            if not ok:
                failures += 1
                print(f"  FAIL (exit {rc})")
            results.append(
                CaseResult(
                    source=rel,
                    ok=ok,
                    rc=rc,
                    status=status,
                    outcome=outcome,
                    fortran_source=str(out_path),
                )
            )
            if not ok:
                if args.maxfail > 0 and failures >= args.maxfail:
                    print(f"Stopped at maxfail={args.maxfail}.")
                    break
                if (not args.terse) and i < total:
                    print("")
                continue
            if (not args.terse) and i < total:
                print("")
            continue
        cp = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="ignore")
        ok = cp.returncode == 0
        outcome = _classify_outcome(ok, cp.stdout or "", cp.stderr or "")

        if ok:
            status = "PASS"
            if (not args.terse) and args.verbose:
                if cp.stdout.strip():
                    print(cp.stdout.rstrip())
                if cp.stderr.strip():
                    print(cp.stderr.rstrip())
        else:
            status = "FAIL"
            failures += 1
            if args.terse:
                print(f"[{i}/{total}] {rel}")
            print(f"  FAIL (exit {cp.returncode})")
            if cp.stdout.strip():
                print(cp.stdout.rstrip())
            if cp.stderr.strip():
                print(cp.stderr.rstrip())
            if args.maxfail > 0 and failures >= args.maxfail:
                results.append(
                    CaseResult(
                        source=rel,
                        ok=ok,
                        rc=cp.returncode,
                        status=status,
                        outcome=outcome,
                        fortran_source=str(out_path),
                    )
                )
                print(f"Stopped at maxfail={args.maxfail}.")
                break

        results.append(
            CaseResult(
                source=rel,
                ok=ok,
                rc=cp.returncode,
                status=status,
                outcome=outcome,
                fortran_source=str(out_path),
            )
        )
        if (not args.terse) and i < total:
            print("")

    print("")
    print("Summary:")
    summary_rows = [r for r in results if (not args.terse or not r.ok)]
    if args.terse and not summary_rows:
        print("(no failures)")
    if summary_rows:
        src_w = max(len("source"), *(len(r.source) for r in summary_rows))
        st_w = max(len("status"), *(len(r.status) for r in summary_rows))
        out_w = max(len("outcome"), *(len(r.outcome) for r in summary_rows))
        f90_w = max(len("Fortran_src"), *(len(r.fortran_source) for r in summary_rows))
        print(f"{'source':<{src_w}}  {'status':<{st_w}}  {'outcome':<{out_w}}  {'Fortran_src':<{f90_w}}")
        for r in summary_rows:
            print(f"{r.source:<{src_w}}  {r.status:<{st_w}}  {r.outcome:<{out_w}}  {r.fortran_source:<{f90_w}}")

    n_pass = sum(1 for r in results if r.ok)
    n_fail = len(results) - n_pass
    print(f"Totals: {len(results)} files, {n_pass} pass, {n_fail} fail")
    print(
        "Outcomes: "
        f"full_pass={sum(1 for r in results if r.outcome == 'full_pass')}  "
        f"transpile_fail={sum(1 for r in results if r.outcome == 'transpile_fail')}  "
        f"original_c_build_fail={sum(1 for r in results if r.outcome == 'original_c_build_fail')}  "
        f"fortran_build_fail={sum(1 for r in results if r.outcome == 'fortran_build_fail')}  "
        f"original_c_run_fail={sum(1 for r in results if r.outcome == 'original_c_run_fail')}  "
        f"fortran_run_fail={sum(1 for r in results if r.outcome == 'fortran_run_fail')}  "
        f"other_fail={sum(1 for r in results if r.outcome == 'other_fail')}"
    )
    elapsed = time.perf_counter() - t0
    print(f"Elapsed: {elapsed:.3f} s")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
