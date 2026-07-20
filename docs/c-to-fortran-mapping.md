# C-to-Fortran language mapping

This page describes how `xc2f.py` maps the supported subset of C to
free-form Fortran. The examples show the usual emitted form after the
transpiler's post-processing passes. Exact formatting may change as the
transpiler develops.

The transpiler is aimed primarily at small, self-contained numerical
programs. It does not attempt to preserve arbitrary C object layouts, pointer
semantics, undefined behavior, or every library and preprocessor feature.
Compile and test generated code before relying on it.

## Types and declarations

| C | Typical emitted Fortran | Notes |
| --- | --- | --- |
| `int`, `short`, `long` | `integer` | Integer widths are not generally reproduced exactly. |
| `unsigned int` | `integer(kind=int64)` | Assignments are masked where needed to reproduce 32-bit wraparound. |
| `float` | `real(kind=sp)` | `sp` is defined with `iso_fortran_env`. |
| `double` | `real(kind=dp)` | `dp` is defined with `iso_fortran_env`. |
| complex floating point | `complex(kind=dp)` | Used by the supported complex-number forms. |
| character strings | `character(...)` | The length may be fixed or allocatable, depending on the declaration. |
| `const` parameter | `intent(in)` | Intent is also inferred from procedure use. |
| file-scope variable | module variable | Shared declarations are placed in `xc2f_mod`. |

Compatible adjacent declarations are combined when this remains readable:

```c
double lower;
double upper;
double tolerance;
```

```fortran
real(kind=dp) :: lower, upper, tolerance
```

Declarations carrying comments or different attributes remain separate.
Long declarations are wrapped using free-form continuation lines.

### Identifier conflicts

Fortran identifiers are case-insensitive, and some valid C names conflict
with Fortran keywords or generated names. The transpiler renames a conflicting
identifier according to its type:

| Kind | Prefix or suffix | Example |
| --- | --- | --- |
| Integer or logical | `i` | `dimension` becomes `idimension` |
| Real | `x` | `dimension` becomes `xdimension` |
| Complex | `z` | `dimension` becomes `zdimension` |
| Character | `s` | `dimension` becomes `sdimension` |
| Procedure | `_f` suffix | a conflicting procedure gets a name such as `name_f` |
| Derived type | `_t` suffix | a conflicting type gets a name such as `name_t` |

If the preferred name already exists, underscores are appended. For example,
when `idimension` is already declared, integer `dimension` becomes
`idimension_`. Definitions and references, including structure components,
are renamed consistently.

## Expressions and operators

The common arithmetic and comparison operators have direct equivalents.

| C | Fortran |
| --- | --- |
| `a + b`, `a - b`, `a * b`, `a / b` | `a + b`, `a - b`, `a * b`, `a / b` |
| `a % b` | `mod(a, b)` |
| `a == b`, `a != b` | `a == b`, `a /= b` |
| `a < b`, `a <= b` | `a < b`, `a <= b` |
| `a && b`, `a || b` | `a .and. b`, `a .or. b` |
| `!condition` | `.not. condition` |
| `condition ? a : b` | `merge(a, b, condition)` |

C integer truth values are converted to comparisons where Fortran requires a
logical value. For example, `!succeeds()` may become `succeeds() == 0` when
`succeeds` returns an integer.

Post-processing removes redundant parentheses, folds simple integer
arithmetic, and applies safe logical identities. For example:

```fortran
xresult((n - 1) + 1) = xend
if ((.false. .or. (tolerance <= 0.0_dp)) .or. (iterations <= 0)) then
```

is simplified to:

```fortran
xresult(n) = xend
if (tolerance <= 0.0_dp .or. iterations <= 0) then
```

## Conditionals and selection

```c
if (x > 0.0) {
    sign = 1;
} else {
    sign = -1;
}
```

```fortran
if (x > 0.0_dp) then
   sign = 1
else
   sign = -1
end if
```

A conservative C `switch` without fallthrough becomes `select case`:

```c
switch (state) {
case 0:
    value = 10;
    break;
default:
    value = 20;
    break;
}
```

```fortran
select case (state)
case (0)
   value = 10
case default
   value = 20
end select
```

Switch fallthrough and conditional `break` patterns inside switch arms are
currently rejected rather than translated incorrectly.

## Loops and array indexing

C arrays are zero-based and Fortran arrays are normally one-based. Without
loop normalization, subscripts are adjusted explicitly:

```c
for (i = 0; i < n; ++i) {
    result[i] = start + i * step;
}
```

```fortran
do i = 0, n-1
   xresult(i+1) = start + i * step
end do
```

By default, a conservative style pass converts eligible array loops to
one-based Fortran and adjusts uses of the induction variable:

```fortran
do i = 1, size(xresult)
   xresult(i) = start + (i - 1) * step
end do
```

Disable that optional transformation with `--no-one-based-loops`. Loops that
cannot be converted safely retain their translated bounds and explicit index
adjustments.

`while` and `do ... while` loops become suitable Fortran `do` forms.
`break` becomes `exit`, and `continue` becomes `cycle`. Supported `goto`
statements retain numeric labels.

For multidimensional arrays, dimensions and subscripts are rewritten to
preserve the intended element access despite the C/Fortran indexing and
storage-order differences. Flattened C indexing such as `a[row*n + column]`
is commonly emitted as `a(row * n + column + 1)`.

## Functions and subroutines

A value-returning C function becomes a Fortran function with an explicit
result variable:

```c
double square(double x) {
    return x * x;
}
```

```fortran
pure function square(x) result(square_result)
real(kind=dp), intent(in) :: x
real(kind=dp) :: square_result
square_result = x * x
end function square
```

A `void` C function becomes a subroutine, and calls use `call`:

```c
void fill(double values[], int n) { /* ... */ }
```

```fortran
subroutine fill(values, n)
! ...
end subroutine fill
```

Recursive C functions are marked `recursive`. The transpiler also performs a
call-aware analysis and marks eligible procedures `pure`. Procedures doing
I/O or other impure work, and their callers, remain impure. Disable purity
promotion with `--no-pure`.

C arguments passed by value are protected with suitable `intent` declarations
or local copies when the C procedure modifies only its private parameter.
Writable pointer and array arguments generally become `intent(inout)`.

## Arrays, pointers, and allocation

Fixed-size C arrays become explicit-shape Fortran arrays. Unsized array
parameters generally become assumed-shape arrays. Initializer lists become
Fortran array constructors.

Pointer translation is contextual rather than a general emulation of C
pointers:

| C use | Typical Fortran representation |
| --- | --- |
| Numeric pointer used as an owned array | `allocatable` array |
| `&array[offset]` passed onward | array section such as `array(offset+1:)` |
| Pointer to a recursive structure node | Fortran `pointer` component or dummy |
| `NULL` test | allocation or association test, as appropriate |
| `malloc` | `allocate` |
| `calloc` | `allocate` followed by zero initialization |
| supported `realloc` growth | temporary allocation plus `move_alloc` |
| `free` | `deallocate` when required |

Pointer arithmetic, aliasing, casts, ownership, and object lifetimes are only
handled for recognized patterns. Code relying on unrestricted C pointer
semantics requires manual review.

## Structures, unions, enums, and typedefs

C structures are represented by Fortran derived types, and member selection
uses `%`:

```c
typedef struct {
    double x;
    double y;
} point;

p.x = 1.0;
```

```fortran
type :: point
   real(kind=dp) :: x
   real(kind=dp) :: y
end type point

p%x = 1.0_dp
```

Nested structures, arrays of structures, structure initializers, returned
structures, recursive structures, and the tested flexible-array-member
patterns are supported. Enums are lowered to integer constants. Tested union
forms are translated, but Fortran derived types do not reproduce C union
storage overlay in general. Do not assume binary layout compatibility with C.

`typedef` names are resolved during type analysis. Function-pointer typedefs
and the tested arrays of function pointers become Fortran procedure interfaces
and procedure-pointer wrappers.

## Strings and command-line arguments

C string literals and supported character-array patterns become Fortran
character values. Common escapes are decoded; embedded quotes are escaped for
Fortran. Arrays of C strings become character arrays whose elements are padded
to a common length.

`argc` and `argv` uses are lowered through
`command_argument_count` and `get_command_argument`. Because executable paths
differ between separately built C and Fortran programs, `argv[0]` is not
expected to be textually identical in `--run-both` comparisons.

## I/O and selected library calls

Supported `printf` and `fprintf` formats become formatted `write` statements.
Literal output without a final newline uses `advance="no"`. Consecutive blank
and textual writes may be compacted into a format beginning with `/`:

```fortran
write(*,"(/,a)") "true covariance:"
```

Unsupported formatting details fall back to an approximation and may receive
an explanatory generated-code comment. Equivalent C and Fortran output can
also differ cosmetically, such as `0.2` versus `.2`.

Recognized stream patterns include `fopen`, `fclose`, `fscanf`, `fprintf`,
`fgetc`, and `feof`. They are lowered to Fortran units, `open`, `close`, and
formatted or character-oriented I/O. Supported `sprintf` and `sscanf` forms
use internal files.

Selected mathematical functions map to Fortran intrinsics. IEEE operations
such as finite checks and quiet NaN creation use `ieee_arithmetic`. When the
same intrinsic import is needed by several procedures, the `use` statement is
placed once at module scope.

Several tested C library operations have purpose-built translations, including
sorting, memory-copy/set patterns, random numbers, and string operations.
This is not a complete implementation of the C standard library.

## Preprocessing

The parser is supplied with declarations for common C library functions, and
the transpiler recognizes a useful subset of simple macro constants and
conditional-compilation patterns. Preprocessor directives and comments are
otherwise removed before parsing.

For code that depends on include expansion, complex macros, compiler-specific
extensions, or build-system definitions, preprocess or adapt the source before
transpilation.

## Generated-code cleanup

Unless `--raw` is selected, post-processing improves the initial translation.
Among other transformations it:

- simplifies integer and logical expressions;
- removes redundant parentheses and unreachable constant-false blocks;
- combines compatible declarations and wraps long lines;
- removes repeated blank lines;
- moves repeated intrinsic imports to module scope;
- infers procedure intent and purity; and
- optionally normalizes eligible loops to one-based indexing.

These passes are intended to improve readability without changing observable
behavior. The C and generated Fortran should still be compiled and exercised
with representative inputs.

## Unsupported and restricted behavior

The following categories should be expected to need source adaptation or
manual Fortran work:

- unrestricted pointer arithmetic and aliasing;
- dependence on exact C structure, union, bit-field, or integer layout;
- switch fallthrough;
- complex macro metaprogramming and compiler-specific C extensions;
- arbitrary variadic functions and unsupported format strings;
- concurrency, atomics, signals, and low-level operating-system interfaces;
- undefined or implementation-defined C behavior; and
- C library calls for which no mapping has been implemented.

The checked-in programs under `tests/corpus`, `tests/fixtures/c`, and
`numerical_methods` are the best executable description of the currently
tested subset. Run `pytest -q` after changing either the transpiler or these
mappings.
