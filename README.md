# C-to-Fortran

`C-to-Fortran` is an experimental source-to-source transpiler for a
practical subset of C, written using Codex and Claude. It translates C
source into readable free-form Fortran, with post-processing passes
that simplify expressions, infer Fortran declarations, promote
eligible procedures to `pure`, and use idiomatic one-based loops when
that transformation is safe.

The project is under active development. It is useful for translating and
studying small numerical programs, but it is not a complete implementation of
the C language. Generated code should be reviewed and tested before production
use.

## Requirements

- Python 3.10 or newer
- [`pycparser`](https://github.com/eliben/pycparser)
- `pytest` for the test suite
- GCC when compiling or comparing the original C programs
- GNU Fortran (`gfortran`) when compiling or running generated Fortran

Both `gcc` and `gfortran` must be available on `PATH` for the integration tests
and the `--run-both`/`--compile-both` workflows.

Create a virtual environment and install the Python dependencies:

```console
python -m venv .venv
```

On Windows:

```console
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
```

On Linux or macOS:

```console
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

## Basic usage

Transpile one C file to `temp.f90`:

```console
python xc2f.py numerical_methods/02_mean.c
```

Choose the output path:

```console
python xc2f.py numerical_methods/02_mean.c --out mean.f90
```

Compile only the generated Fortran:

```console
python xc2f.py numerical_methods/02_mean.c --compile
```

Compile and run both versions:

```console
python xc2f.py numerical_methods/02_mean.c --run-both
```

Compare their output:

```console
python xc2f.py numerical_methods/02_mean.c --run-both --run-diff
```

Use `--debug` with a Fortran build/run option to enable runtime checks,
floating-point traps, debug symbols, and backtraces.

Eligible zero-based C loops are emitted as idiomatic one-based Fortran loops by
default. Disable this style transformation with:

```console
python xc2f.py input.c --no-one-based-loops
```

Run `python xc2f.py --help` for the complete option list.

## Batch processing

`xc2f_batch.py` accepts files, directories, glob patterns, and `@list` files.
On Windows it expands glob patterns itself, so this works from `cmd.exe` and
PowerShell:

```console
python xc2f_batch.py numerical_methods/*.c --run-both
```

Failures are reported per file and processing continues with the next C file
by default. Use `--maxfail N` to stop after a chosen number of failures and
`--terse` to show only failures and final totals.

Regenerate and compile the checked-in numerical-method translations with:

```console
python xc2f_batch.py numerical_methods/*.c \
  --out-dir numerical_methods/fortran --compile --terse
```

In Windows `cmd.exe`, enter the command on one line rather than using `\` as a
line continuation.

## Numerical examples

[`numerical_methods`](numerical_methods) contains 14 independent C programs
covering:

- sum, mean, minimum, and maximum;
- variance, standard deviation, dot product, and vector norm;
- linspace generation and Horner polynomial evaluation;
- centered differentiation;
- trapezoidal and Simpson integration;
- bisection and Newton root finding; and
- Gaussian elimination.

The corresponding generated Fortran snapshots are in
[`numerical_methods/fortran`](numerical_methods/fortran). They are kept in the
repository so the C and Fortran versions can be inspected side by side.

## Tests

Install the development dependencies and run:

```console
pytest -q
```

Tests that require unavailable external compilers are skipped automatically.
With both GCC and GNU Fortran installed, the integration tests compile and run
representative C and generated Fortran programs and compare their behavior.

The pytest corpus includes:

- the numbered examples in `tests/corpus`, from `001_hello_world.c` through
  `100_state_machine.c`;
- larger integration examples `xnumerical.c`, `xmv_mix.c`, and
  `xmatrix_stats.c`;
- the C examples under `numerical_methods`; and
- focused adaptations under `tests/fixtures/c`.

These sources, the complete `tests` directory, `pytest.ini`, and
`requirements-dev.txt` are required for the complete test suite.

Useful subsets include:

```console
pytest -q -m "not integration"
pytest -q -m integration
pytest -q -m corpus
```

## Project layout

| Path | Purpose |
| --- | --- |
| `xc2f.py` | Main transpiler and single-file CLI |
| `xc2f_batch.py` | Multi-file batch driver |
| `fortran_*.py` | Fortran scanning, formatting, semantic, build, and refactoring helpers |
| `x*.py` | Focused post-processing and analysis helpers used by the transpiler |
| `tests/corpus` | Numbered C language feature corpus used by pytest |
| `numerical_methods/*.c` | Standalone numerical C examples |
| `numerical_methods/fortran/*.f90` | Generated Fortran snapshots |
| `tests` | Unit, corpus, and compiler-backed integration tests |
| `requirements*.txt`, `pytest.ini` | Runtime and test configuration |

## Notes and limitations

- Translation support is intentionally partial and driven by the included
  examples and tests.
- C and Fortran runtimes can format equivalent floating-point output
  differently, for example `0.2` versus `.2`.
- Some compiler flags are GNU-specific.
- Legacy K&R C sources may require an older dialect such as `-std=gnu89` when
  compiled with a recent GCC.

