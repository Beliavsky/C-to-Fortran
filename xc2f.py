#!/usr/bin/env python3
"""xc2f.py: small C->Fortran transpiler for a practical C subset.

Current focus: enough coverage to translate xfactors.c into compilable Fortran.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import re
import subprocess
import sys
import tempfile
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

from pycparser import c_ast, c_parser
import fortran_scan as fscan
import fortran_post as fpost
import fortran_refactor as fref
import xadvance
import xalloc_assign
import xunused
import xpure


PRELUDE = """
typedef unsigned long size_t;
typedef int FILE;
typedef signed char int8_t;
typedef unsigned char uint8_t;
typedef short int16_t;
typedef unsigned short uint16_t;
typedef int int32_t;
typedef unsigned int uint32_t;
typedef long long int64_t;
typedef unsigned long long uint64_t;
typedef long time_t;
typedef int bool;
typedef double complex_double;
struct tm;
void *malloc(size_t);
void *realloc(void *, size_t);
void free(void *);
double sqrt(double);
double floor(double);
time_t time(time_t *);
struct tm *localtime(const time_t *);
size_t strftime(char *, size_t, const char *, const struct tm *);
FILE *fopen(const char *, const char *);
int fclose(FILE *);
int fprintf(FILE *, const char *, ...);
int fscanf(FILE *, const char *, ...);
int printf(const char *, ...);
double creal(complex_double);
double cimag(complex_double);
""".strip()

DEFAULT_GFORTRAN_FLAGS = [
    "-O0",
    "-Wall",
    "-Wfatal-errors",
    "-Werror=unused-parameter",
    "-Werror=unused-variable",
    "-Werror=unused-function",
    "-Wno-maybe-uninitialized",
    "-Wno-surprising",
    "-fbounds-check",
    "-static",
    "-fbacktrace",
    "-g",
    "-fmodule-private",
]

PRELUDE_LINE_COUNT = len(PRELUDE.splitlines())


def _xc2f_added_comment(text: str) -> str:
    """Return a machine-detectable xc2f-generated comment line."""
    return f"! added by xc2f.py: {text}"


def _prepend_origin_comment(fsrc: str, sources: List[Path]) -> str:
    """Add a source-origin comment at the top of generated Fortran."""
    names = ", ".join(p.name for p in sources)
    header = f"! created by xc2f.py from {names}\n"
    if fsrc.startswith(header):
        return fsrc
    return header + fsrc


@dataclass
class VarInfo:
    ftype: str
    alloc: bool = False
    shape: Optional[Tuple[str, ...]] = None
    # True for C strings (char arrays/pointers) lowered to Fortran character
    # entities: scalar strings use substring indexing, arrays of strings use
    # ordinary element indexing.
    char_string: bool = False
    # True for C unsigned 32-bit integers: stored as integer(int64) and every
    # assignment is masked to reproduce C wraparound semantics.
    unsigned: bool = False
    # True for arrays of C function pointers, lowered to an array of a
    # procedure-pointer wrapper type.
    funcptr_array: bool = False
    # True for pointers to recursive structs (linked lists, trees): lowered to
    # Fortran POINTER scalars with => assignment and associated() tests.
    struct_ptr: bool = False


@dataclass
class StructDef:
    name: str
    # Each field is (name, fortran_type, shape). `shape` is a Fortran extent
    # string (e.g. "2" or "3, 3") for array fields, or None for scalars.
    fields: List[Tuple[str, str, Optional[str]]]


_STRUCT_TYPEDEFS: Set[str] = set()

# Struct name -> flexible-array-member field name (C `double data[];`).
_STRUCT_FLEX_MEMBERS: Dict[str, str] = {}

# Structs containing self-referential pointer members (linked lists, trees).
_STRUCT_RECURSIVE: Set[str] = set()
# Struct name -> its pointer-component field names.
_STRUCT_PTR_FIELDS: Dict[str, Set[str]] = {}
# Struct name -> C pointer fields lowered to allocatable array components.
_STRUCT_ALLOC_FIELDS: Dict[str, Set[str]] = {}

# Common <limits.h>/<stdint.h> constants lowered to literal values.
_C_LIMIT_CONSTANTS: Dict[str, str] = {
    "INT_MAX": "2147483647",
    "INT_MIN": "(-2147483647 - 1)",
    "UINT_MAX": "4294967295_int64",
    "LONG_MAX": "9223372036854775807_int64",
    "SHRT_MAX": "32767",
    "SHRT_MIN": "(-32768)",
    "USHRT_MAX": "65535",
    "CHAR_BIT": "8",
    "SCHAR_MAX": "127",
    "SCHAR_MIN": "(-128)",
    "UCHAR_MAX": "255",
}


def strip_preprocessor_and_comments(text: str) -> str:
    lines = []
    in_block = False
    i = 0
    while i < len(text):
        if not in_block and text[i : i + 2] == "/*":
            in_block = True
            i += 2
            continue
        if in_block and text[i : i + 2] == "*/":
            in_block = False
            i += 2
            continue
        if not in_block:
            lines.append(text[i])
        i += 1
    s = "".join(lines)
    out = []
    skip_cont = False
    for line in s.splitlines():
        t = line.strip()
        # A preprocessor directive continued with a trailing backslash carries
        # over to following physical lines; drop those continuation lines too.
        if skip_cont:
            skip_cont = line.rstrip().endswith("\\")
            continue
        if t.startswith("#"):
            skip_cont = line.rstrip().endswith("\\")
            continue
        if "//" in line:
            line = line.split("//", 1)[0]
        out.append(line)
    return "\n".join(out)


def strip_preprocessor_only(text: str) -> str:
    """Remove preprocessor lines but keep comments."""
    out = []
    skip_cont = False
    for line in text.splitlines():
        if skip_cont:
            skip_cont = line.rstrip().endswith("\\")
            continue
        if line.strip().startswith("#"):
            skip_cont = line.rstrip().endswith("\\")
            continue
        out.append(line)
    return "\n".join(out)


def normalize_fortran_d_exponents(text: str) -> str:
    """Accept Fortran-style D exponents in C-like numeric literals.

    This keeps line and column positions stable by rewriting only the single
    exponent marker character.
    """
    def repl(m: re.Match[str]) -> str:
        token = m.group(0)
        if "d" in token:
            return token.replace("d", "e", 1)
        return token.replace("D", "E", 1)

    return re.sub(
        r"(?<![A-Za-z0-9_])(?:\d+\.\d*|\.\d+|\d+)[dD][+\-]?\d+(?![A-Za-z0-9_])",
        repl,
        text,
    )


def normalize_c_complex_types(text: str) -> str:
    """Replace C99 complex spellings with parser-friendly typedef names."""
    return re.sub(r"\bdouble\s+(?:_Complex|complex)\b", "complex_double", text)


def _decode_c_string_literal(literal: str) -> Optional[str]:
    """Decode a pycparser C string token to its character value."""
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


def _literal_printf_text(text: str) -> Optional[str]:
    """Expand printf's literal ``%%``; reject conversions needing arguments."""
    pieces: List[str] = []
    i = 0
    while i < len(text):
        if text[i] != "%":
            pieces.append(text[i])
            i += 1
        elif i + 1 < len(text) and text[i + 1] == "%":
            pieces.append("%")
            i += 2
        else:
            return None
    return "".join(pieces)


def _fortran_character_expr(text: str) -> str:
    """Return a portable Fortran expression for arbitrary decoded C text."""
    terms: List[str] = []
    printable: List[str] = []

    def flush_printable() -> None:
        if printable:
            terms.append('"' + "".join(printable).replace('"', '""') + '"')
            printable.clear()

    for char in text:
        code = ord(char)
        if char in {"\n", "\r", "\t", "\v", "\f", "\b", "\a"} or code == 0:
            flush_printable()
            terms.append(f"achar({code})")
        else:
            printable.append(char)
    flush_printable()
    return " // ".join(terms) if terms else '""'


def is_language_specific_comment(s: str) -> bool:
    low = s.lower()
    banned = (
        "malloc", "free", "calloc", "realloc", "pointer", "null",
        "size_t", "printf", "scanf",
    )
    return any(tok in low for tok in banned)


def extract_preserved_comments(text: str) -> Dict[int, List[str]]:
    """Extract non-language-specific comments keyed by source line number."""
    out: Dict[int, List[str]] = defaultdict(list)
    lines = text.splitlines()
    in_block = False
    block_start_line = 0
    block_buf: List[str] = []

    def _flush_block(line_no: int) -> None:
        nonlocal block_buf
        for raw in block_buf:
            t = raw.strip()
            if not t:
                continue
            if t.startswith("*"):
                t = t[1:].strip()
            if t and not is_language_specific_comment(t):
                out[line_no].append(t)
        block_buf = []

    for i, raw in enumerate(lines, start=1):
        line = raw
        if in_block:
            if "*/" in line:
                before, _after = line.split("*/", 1)
                block_buf.append(before)
                _flush_block(i)
                in_block = False
            else:
                block_buf.append(line)
            continue

        if "/*" in line:
            before, after = line.split("/*", 1)
            if "*/" in after:
                mid, _tail = after.split("*/", 1)
                t = mid.strip().lstrip("*").strip()
                # Skip trailing prototype comments such as:
                #   float f(...); /* comment */
                if ");" in before:
                    t = ""
                if t and not is_language_specific_comment(t):
                    out[i].append(t)
            else:
                in_block = True
                block_start_line = i
                block_buf = [after]
            # handle // on prefix if present
            if "//" in before:
                c = before.split("//", 1)[1].strip()
                if c and not is_language_specific_comment(c):
                    out[i].append(c)
            continue

        if "//" in line:
            c = line.split("//", 1)[1].strip()
            if c and not is_language_specific_comment(c):
                out[i].append(c)

    if in_block and block_buf:
        _flush_block(block_start_line or 1)
    return out


def extract_c_function_arg_comments(text: str) -> Dict[str, Dict[str, str]]:
    """Extract per-function argument comments of form `name: doc` from C.

    Looks in the contiguous comment block immediately after a function
    definition header line.
    """
    out: Dict[str, Dict[str, str]] = {}
    lines = text.splitlines()
    head_re = re.compile(r"^\s*[a-z_][\w\s\*]*\b([a-z_]\w*)\s*\([^;]*\)\s*\{\s*$", re.IGNORECASE)
    cmt_re = re.compile(r"^\s*/\*\s*(.*?)\s*\*/\s*$")
    arg_re = re.compile(r"^([a-z_]\w*)\s*:\s*(.+)$", re.IGNORECASE)

    i = 0
    while i < len(lines):
        m = head_re.match(lines[i])
        if not m:
            i += 1
            continue
        fname = m.group(1).lower()
        amap: Dict[str, str] = {}
        j = i + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            mc = cmt_re.match(lines[j])
            if not mc:
                break
            txt = mc.group(1).strip()
            ma = arg_re.match(txt)
            if ma:
                amap[ma.group(1).lower()] = ma.group(2).strip()
            j += 1
        if amap:
            out[fname] = amap
        i = j
    return out


def extract_c_function_header_comments(text: str) -> Dict[str, str]:
    """Extract first non-arg comment from each C function's leading comment block."""
    out: Dict[str, str] = {}
    lines = text.splitlines()
    head_re = re.compile(r"^\s*[a-z_][\w\s\*]*\b([a-z_]\w*)\s*\([^;]*\)\s*\{\s*$", re.IGNORECASE)
    cmt_re = re.compile(r"^\s*/\*\s*(.*?)\s*\*/\s*$")
    arg_re = re.compile(r"^[a-z_]\w*\s*:\s*", re.IGNORECASE)
    i = 0
    while i < len(lines):
        m = head_re.match(lines[i])
        if not m:
            i += 1
            continue
        fname = m.group(1).lower()
        j = i + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            mc = cmt_re.match(lines[j])
            if not mc:
                break
            txt = mc.group(1).strip()
            if txt and not arg_re.match(txt):
                out[fname] = txt
                break
            j += 1
        i = j
    return out


def c_to_ftype(type_decl: c_ast.Node) -> Tuple[str, bool]:
    node = type_decl
    alloc = False
    ptr_depth = 0
    while isinstance(node, (c_ast.TypeDecl, c_ast.PtrDecl, c_ast.ArrayDecl)):
        if isinstance(node, c_ast.PtrDecl):
            alloc = True
            ptr_depth += 1
            node = node.type
        elif isinstance(node, c_ast.ArrayDecl):
            node = node.type
        else:
            node = node.type
    if isinstance(node, c_ast.IdentifierType):
        names = [n.lower() for n in node.names]
        if "file" in names:
            return "integer", False
        if "void" in names:
            return "void", alloc
        if "char" in names:
            return "character(len=*)", False
        if "double" in names:
            return "real(kind=dp)", alloc
        if "complex_double" in names:
            return "complex(kind=dp)", alloc
        if "float" in names:
            return "real(kind=sp)", alloc
        if len(names) == 1 and names[0] in _STRUCT_TYPEDEFS:
            return f"type({names[0]})", alloc
        return "integer", alloc
    if isinstance(node, (c_ast.Struct, c_ast.Union)):
        sname = (node.name or "").lower()
        if sname:
            return f"type({sname})", alloc
    return "integer", alloc


def dummy_array_rank(type_decl: c_ast.Node) -> int:
    """Count the array rank of a C parameter type (arrays + pointers)."""
    rank = 0
    node = type_decl
    while node is not None:
        if isinstance(node, c_ast.ArrayDecl):
            rank += 1
            node = node.type
        elif isinstance(node, c_ast.PtrDecl):
            rank += 1
            node = node.type
        else:
            break
    return rank


def type_is_ptr_or_array(type_decl: c_ast.Node) -> bool:
    node = type_decl
    while node is not None:
        if isinstance(node, (c_ast.PtrDecl, c_ast.ArrayDecl)):
            return True
        node = getattr(node, "type", None)
    return False


def type_has_const(type_decl: c_ast.Node) -> bool:
    """Return True if C declaration type carries a const qualifier."""
    node = type_decl
    while node is not None:
        quals = getattr(node, "quals", None)
        if quals and any(str(q).lower() == "const" for q in quals):
            return True
        node = getattr(node, "type", None)
    return False


def _classify_char_decl(type_decl: c_ast.Node) -> Optional[str]:
    """Classify a C declaration type as a char-string entity.

    Returns "scalar" for `char x[]` / `char x[64]` / `char *x` (one string),
    "array" for `char *x[]` (an array of strings), or None when the base type
    is not char or the declaration is a plain `char` scalar.
    """
    wrappers: List[str] = []
    node = type_decl
    while isinstance(node, (c_ast.ArrayDecl, c_ast.PtrDecl)):
        wrappers.append("arr" if isinstance(node, c_ast.ArrayDecl) else "ptr")
        node = node.type
    if not isinstance(node, c_ast.TypeDecl) or not isinstance(node.type, c_ast.IdentifierType):
        return None
    if "char" not in [n.lower() for n in node.type.names]:
        return None
    if not wrappers:
        return None  # plain `char c` scalar, not a string
    if len(wrappers) == 1:
        return "scalar"
    if wrappers == ["arr", "ptr"]:
        return "array"
    return None


def _char_array_decl_len(type_decl: c_ast.Node) -> Optional[str]:
    """Return the declared buffer length of `char x[N]`, if constant."""
    if isinstance(type_decl, c_ast.ArrayDecl) and type_decl.dim is not None:
        return _render_dim_expr(type_decl.dim)
    return None


def _render_dim_expr(node: c_ast.Node) -> Optional[str]:
    """Render a constant array-dimension expression (literal, macro, or simple
    arithmetic) to Fortran text, or None if it is not a compile-time extent."""
    if isinstance(node, c_ast.Constant):
        return Emitter._normalize_int_literal(node.value) or node.value
    if isinstance(node, c_ast.ID):
        return node.name
    if isinstance(node, c_ast.BinaryOp):
        left = _render_dim_expr(node.left)
        right = _render_dim_expr(node.right)
        if left is not None and right is not None and node.op in ("+", "-", "*", "/"):
            return f"({left} {node.op} {right})"
    return None


def gather_decls(node: c_ast.Node, out: Dict[str, VarInfo]) -> None:
    if isinstance(node, c_ast.Decl):
        if isinstance(node.type, c_ast.FuncDecl):
            return
        ftype, alloc = c_to_ftype(node.type)
        if node.name:
            # `int (*ops[3])(int, int)`: array of function pointers becomes an
            # array of the procedure-pointer wrapper type.
            if (
                isinstance(node.type, c_ast.ArrayDecl)
                and isinstance(node.type.type, c_ast.PtrDecl)
                and isinstance(node.type.type.type, c_ast.FuncDecl)
            ):
                n_txt = _render_dim_expr(node.type.dim) if node.type.dim is not None else None
                if n_txt is None and isinstance(node.init, c_ast.InitList):
                    n_txt = str(len(node.init.exprs or []))
                if n_txt is not None:
                    out[node.name] = VarInfo(
                        ftype="type(c2f_procptr)",
                        shape=(n_txt,),
                        funcptr_array=True,
                    )
                    for _, child in node.children():
                        gather_decls(child, out)
                    return
            char_kind = _classify_char_decl(node.type)
            if char_kind == "scalar":
                buf_len = _char_array_decl_len(node.type)
                if node.init is None and buf_len is not None:
                    # Uninitialized buffer (e.g. sprintf target): fixed length.
                    out[node.name] = VarInfo(
                        ftype=f"character(len={buf_len})", char_string=True
                    )
                else:
                    # Initialized string: deferred length holds the exact value.
                    out[node.name] = VarInfo(
                        ftype="character(len=:)", alloc=True, char_string=True
                    )
                for _, child in node.children():
                    gather_decls(child, out)
                return
            if char_kind == "array":
                n_elems: Optional[str] = None
                if isinstance(node.type, c_ast.ArrayDecl) and node.type.dim is not None:
                    n_elems = _render_dim_expr(node.type.dim)
                elem_len = 1
                if isinstance(node.init, c_ast.InitList):
                    exprs = node.init.exprs or []
                    if n_elems is None:
                        n_elems = str(len(exprs))
                    for e in exprs:
                        if isinstance(e, c_ast.Constant) and e.type == "string":
                            decoded = _decode_c_string_literal(e.value)
                            if decoded is not None:
                                elem_len = max(elem_len, len(decoded))
                if n_elems is not None:
                    out[node.name] = VarInfo(
                        ftype=f"character(len={elem_len})",
                        shape=(n_elems,),
                        char_string=True,
                    )
                    for _, child in node.children():
                        gather_decls(child, out)
                    return
            dims: List[str] = []
            unsized_array = False
            type_node = node.type
            while isinstance(type_node, c_ast.ArrayDecl):
                if type_node.dim is None:
                    dims = []
                    unsized_array = True
                    break
                dim_txt = _render_dim_expr(type_node.dim)
                if dim_txt is None:
                    dims = []
                    break
                dims.append(dim_txt)
                type_node = type_node.type
            # `int x[] = {a, b, c}`: infer the extent from the initializer.
            if unsized_array and isinstance(node.init, c_ast.InitList):
                dims = [str(len(node.init.exprs or []))]
            # A pointer to a struct with a flexible array member is one object
            # whose payload lives in the allocatable component: keep it scalar.
            mflex = re.match(r"^type\(([^)]+)\)$", ftype, re.IGNORECASE)
            if alloc and mflex is not None and mflex.group(1).lower() in _STRUCT_FLEX_MEMBERS:
                alloc = False
            # A pointer to a recursive struct (list/tree node) becomes a true
            # Fortran POINTER scalar.
            is_struct_ptr = False
            if alloc and mflex is not None and mflex.group(1).lower() in _STRUCT_RECURSIVE:
                alloc = False
                is_struct_ptr = True
            # C unsigned int: widen to int64 and mask assignments so C's
            # modulo-2^32 wraparound is reproduced.
            is_unsigned = False
            if ftype == "integer" and not alloc and not dims:
                tnode = node.type
                while isinstance(tnode, (c_ast.ArrayDecl, c_ast.PtrDecl, c_ast.TypeDecl)) and not isinstance(tnode, c_ast.PtrDecl):
                    if isinstance(tnode, c_ast.TypeDecl):
                        tnode = tnode.type
                        break
                    tnode = tnode.type
                if isinstance(tnode, c_ast.IdentifierType) and "unsigned" in [x.lower() for x in tnode.names]:
                    ftype = "integer(kind=int64)"
                    is_unsigned = True
            out[node.name] = VarInfo(
                ftype=ftype,
                alloc=alloc,
                shape=tuple(reversed(dims)) if dims else None,
                unsigned=is_unsigned,
                struct_ptr=is_struct_ptr,
            )
    for _, child in node.children():
        gather_decls(child, out)


def collect_struct_typedefs(ast: c_ast.FileAST) -> Dict[str, StructDef]:
    """Collect typedef and named ``struct``/``union`` definitions.

    A flexible array member (`double data[];`) is recorded with shape ":" and
    becomes an allocatable component. Its name per struct goes into
    ``_STRUCT_FLEX_MEMBERS``.
    """
    out: Dict[str, StructDef] = {}
    _STRUCT_FLEX_MEMBERS.clear()
    _STRUCT_RECURSIVE.clear()
    _STRUCT_PTR_FIELDS.clear()
    _STRUCT_ALLOC_FIELDS.clear()
    for ext in ast.ext:
        name: Optional[str] = None
        struct: Optional[c_ast.Node] = None
        if isinstance(ext, c_ast.Typedef):
            type_node = ext.type
            if isinstance(type_node, c_ast.TypeDecl) and isinstance(type_node.type, (c_ast.Struct, c_ast.Union)):
                name = ext.name
                struct = type_node.type
        elif isinstance(ext, c_ast.Decl) and isinstance(ext.type, (c_ast.Struct, c_ast.Union)):
            name = ext.type.name
            struct = ext.type
        if not name or struct is None or not struct.decls:
            continue
        fields: List[Tuple[str, str, Optional[str]]] = []
        for d in struct.decls or []:
            if not isinstance(d, c_ast.Decl) or not d.name:
                continue
            ftype, _alloc = c_to_ftype(d.type)
            if isinstance(d.type, c_ast.ArrayDecl) and d.type.dim is None:
                # Flexible array member -> allocatable component.
                fields.append((d.name, ftype, ":"))
                _STRUCT_FLEX_MEMBERS[name.lower()] = d.name
                continue
            if isinstance(d.type, c_ast.PtrDecl):
                base = d.type.type
                while isinstance(base, c_ast.TypeDecl):
                    base = base.type
                if isinstance(base, (c_ast.Struct, c_ast.Union)) and (base.name or "").lower() == name.lower():
                    # Self-referential pointer member (list/tree link).
                    fields.append((d.name, f"type({name.lower()})", "*"))
                    _STRUCT_RECURSIVE.add(name.lower())
                    _STRUCT_PTR_FIELDS.setdefault(name.lower(), set()).add(d.name.lower())
                    continue
                # Ordinary C pointer fields are used as dynamically sized
                # arrays.  They must retain both rank and allocation status in
                # the derived type (for example `double *weight`).
                if _alloc and not ftype.lower().startswith("character"):
                    fields.append((d.name, ftype, ":"))
                    _STRUCT_ALLOC_FIELDS.setdefault(name.lower(), set()).add(d.name.lower())
                    continue
            dims: List[str] = []
            type_node = d.type
            while isinstance(type_node, c_ast.ArrayDecl):
                if isinstance(type_node.dim, c_ast.Constant):
                    dims.append(type_node.dim.value)
                else:
                    dims = []
                    break
                type_node = type_node.type
            shape = ", ".join(reversed(dims)) if dims else None
            fields.append((d.name, ftype, shape))
        out[name.lower()] = StructDef(name=name.lower(), fields=fields)
    return out


def collect_enum_constants(node: c_ast.Node) -> Dict[str, int]:
    """Collect integer values from C enums with literal or implicit values."""
    out: Dict[str, int] = {}

    def visit(current: c_ast.Node) -> None:
        if isinstance(current, c_ast.Enum) and current.values is not None:
            next_value = 0
            for enumerator in current.values.enumerators or []:
                if enumerator.value is not None:
                    value_node = enumerator.value
                    sign = 1
                    if isinstance(value_node, c_ast.UnaryOp) and value_node.op == "-":
                        sign = -1
                        value_node = value_node.expr
                    if not isinstance(value_node, c_ast.Constant):
                        raise NotImplementedError("Only literal enum values are supported")
                    try:
                        next_value = sign * int(value_node.value, 0)
                    except ValueError as exc:
                        raise NotImplementedError("Only integer enum values are supported") from exc
                out[enumerator.name] = next_value
                next_value += 1
        for _name, child in current.children():
            if isinstance(child, c_ast.Node):
                visit(child)

    visit(node)
    return out


def collect_define_constants(text: str) -> Dict[str, Tuple[str, str]]:
    """Collect object-like ``#define NAME literal`` numeric macros.

    Returns a mapping of macro name to ``(fortran_type, fortran_value)``.
    Function-like macros and non-numeric values are ignored (they are handled
    elsewhere or left to the C preprocessor stripping).
    """
    out: Dict[str, Tuple[str, str]] = {}
    define_re = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\s+(.+?)\s*$")
    int_re = re.compile(r"^[+-]?\d+[uUlL]*$")
    float_re = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eEdD][+-]?\d+)?[fFlL]*$")
    for line in text.splitlines():
        m = define_re.match(line)
        if not m:
            continue
        name = m.group(1)
        value = m.group(2).strip()
        # Skip function-like macros: `#define NAME(x) ...`.
        if re.match(r"^\s*#\s*define\s+[A-Za-z_]\w*\s*\(", line):
            continue
        if int_re.match(value):
            digits = re.sub(r"[uUlL]+$", "", value)
            out[name] = ("integer", digits)
        elif float_re.match(value):
            body = re.sub(r"[fFlL]+$", "", value)
            body = body.replace("D", "e").replace("d", "e")
            out[name] = ("real(kind=dp)", f"{body}_dp")
    return out


def _split_top_level_commas(s: str) -> List[str]:
    """Split on commas not nested inside brackets, quotes."""
    parts: List[str] = []
    cur: List[str] = []
    depth = 0
    in_s = False
    in_d = False
    for ch in s:
        if ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "'" and not in_d:
            in_s = not in_s
        if not in_s and not in_d:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(cur))
                cur = []
                continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def collect_func_macros(text: str) -> Dict[str, Tuple[List[str], str]]:
    """Collect object-like function macros ``#define NAME(a, b) body``.

    Excludes ``_Generic`` macros (handled separately). Returns name ->
    (params, body_text).
    """
    out: Dict[str, Tuple[List[str], str]] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*#\s*define\b", line):
            full = line
            while full.rstrip().endswith("\\") and i + 1 < len(lines):
                full = full.rstrip()[:-1] + " " + lines[i + 1]
                i += 1
            m = re.match(r"^\s*#\s*define\s+([A-Za-z_]\w*)\(([^)]*)\)\s+(.+)$", full)
            if m is not None and "_Generic" not in m.group(3):
                params = [p.strip() for p in m.group(2).split(",") if p.strip()]
                out[m.group(1)] = (params, m.group(3).strip())
        i += 1
    return out


def expand_function_macros(src: str, macros: Dict[str, Tuple[List[str], str]]) -> str:
    """Textually expand function-like macro invocations in C source."""
    if not macros:
        return src
    for _ in range(16):  # iterate to expand nested invocations
        changed = False
        for name, (params, body) in macros.items():
            call_re = re.compile(rf"\b{re.escape(name)}\s*\(")
            result: List[str] = []
            i = 0
            while i < len(src):
                m = call_re.search(src, i)
                if m is None:
                    result.append(src[i:])
                    break
                depth = 0
                j = m.end() - 1
                instr: Optional[str] = None
                while j < len(src):
                    ch = src[j]
                    if instr is not None:
                        if ch == instr:
                            instr = None
                    elif ch in ("'", '"'):
                        instr = ch
                    elif ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                if j >= len(src):
                    result.append(src[i:])
                    break
                argv = _split_top_level_commas(src[m.end():j])
                if len(params) == len(argv) and (params or not argv):
                    expanded = body
                    for pname, aval in zip(params, argv):
                        expanded = re.sub(rf"\b{re.escape(pname)}\b", f"({aval.strip()})", expanded)
                    result.append(src[i:m.start()])
                    result.append(f"({expanded})")
                    changed = True
                    i = j + 1
                else:
                    result.append(src[i:j + 1])
                    i = j + 1
            src = "".join(result)
        if not changed:
            break
    return src


def collect_generic_macros(text: str) -> Dict[str, Dict[str, str]]:
    """Collect ``#define NAME(x) _Generic(...)`` type-selection macros.

    Returns name -> {c_type_or_'default': result_token}, where result_token is
    the (Fortran-compatible) literal to emit for that type.
    """
    out: Dict[str, Dict[str, str]] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*#\s*define\b", line):
            full = line
            while full.rstrip().endswith("\\") and i + 1 < len(lines):
                full = full.rstrip()[:-1] + " " + lines[i + 1]
                i += 1
            m = re.match(r"^\s*#\s*define\s+([A-Za-z_]\w*)\s*\(\s*[A-Za-z_]\w*\s*\)\s*(.+)$", full)
            if m is not None and "_Generic" in m.group(2):
                gm = re.search(r"_Generic\s*\((.*)\)\s*$", m.group(2).strip())
                if gm is not None:
                    mapping: Dict[str, str] = {}
                    for entry in _split_top_level_commas(gm.group(1))[1:]:
                        if ":" in entry:
                            ty, res = entry.split(":", 1)
                            mapping[ty.strip().lower()] = res.strip()
                    if mapping:
                        out[m.group(1).lower()] = mapping
        i += 1
    return out


def _has_void_ptr_param(fn: c_ast.FuncDef) -> bool:
    """True when the C function takes any `void *` parameter."""
    fdecl = fn.decl.type
    if not isinstance(fdecl, c_ast.FuncDecl) or fdecl.args is None:
        return False
    for p in fdecl.args.params:
        if not isinstance(p, c_ast.Decl):
            continue
        node = p.type
        depth = 0
        while isinstance(node, (c_ast.PtrDecl, c_ast.TypeDecl)):
            if isinstance(node, c_ast.PtrDecl):
                depth += 1
            node = node.type
        if depth >= 1 and isinstance(node, c_ast.IdentifierType) and "void" in [x.lower() for x in node.names]:
            return True
    return False


def _collect_qsort_elem_kinds(ast_root: c_ast.FileAST) -> Set[str]:
    """Element kinds ("int"/"real") sorted via qsort() anywhere in the file."""
    kinds: Set[str] = set()
    for e in ast_root.ext:
        if not isinstance(e, c_ast.FuncDef):
            continue
        lm: Dict[str, VarInfo] = {}
        gather_decls(e.body, lm)

        def visit(node: c_ast.Node) -> None:
            if (
                isinstance(node, c_ast.FuncCall)
                and isinstance(node.name, c_ast.ID)
                and node.name.name == "qsort"
                and node.args is not None
                and node.args.exprs
                and isinstance(node.args.exprs[0], c_ast.ID)
            ):
                info = lm.get(node.args.exprs[0].name)
                ft = (info.ftype if info is not None else "integer").lower()
                kinds.add("real" if ft.startswith("real") else "int")
            for _k, child in node.children():
                if isinstance(child, c_ast.Node):
                    visit(child)

        visit(e.body)
    return kinds


def emit_qsort_helper(em: Emitter, kind: str) -> None:
    """Emit an ascending in-place insertion sort standing in for C qsort."""
    tname = "integer" if kind == "int" else "real(kind=dp)"
    em.emit(f"subroutine c2f_sort_{kind}(a)")
    em.emit("! ascending sort (C qsort call; comparator assumed ascending)")
    em.emit(f"{tname}, intent(inout) :: a(:)")
    em.emit("integer :: i, j")
    em.emit(f"{tname} :: key")
    em.emit("do i = 2, size(a)")
    em.emit("   key = a(i)")
    em.emit("   j = i - 1")
    em.emit("   do")
    em.emit("      if (j < 1) exit")
    em.emit("      if (a(j) <= key) exit")
    em.emit("      a(j+1) = a(j)")
    em.emit("      j = j - 1")
    em.emit("   end do")
    em.emit("   a(j+1) = key")
    em.emit("end do")
    em.emit(f"end subroutine c2f_sort_{kind}")


def _body_has_unsigned_locals(body: c_ast.Node) -> bool:
    """True when the body declares any C unsigned-int local."""
    probe: Dict[str, VarInfo] = {}
    gather_decls(body, probe)
    return any(info.unsigned for info in probe.values())


def _subtree_has_funccall(node: c_ast.Node) -> bool:
    """True when the expression subtree contains any function call."""
    if isinstance(node, c_ast.FuncCall):
        return True
    for _k, child in node.children():
        if isinstance(child, c_ast.Node) and _subtree_has_funccall(child):
            return True
    return False


def get_id_name(node: c_ast.Node) -> Optional[str]:
    if isinstance(node, c_ast.ID):
        return node.name
    return None


def has_array_ref_of(node: c_ast.Node, name: str) -> bool:
    """True if subtree contains ArrayRef whose base is identifier `name`."""
    target = name.lower()
    if isinstance(node, c_ast.ArrayRef):
        base = node.name
        if isinstance(base, c_ast.ID) and base.name.lower() == target:
            return True
    for _k, child in node.children():
        if isinstance(child, c_ast.Node) and has_array_ref_of(child, name):
            return True
    return False


def is_forwarded_to_array_parameter(
    node: c_ast.Node,
    name: str,
    array_param_funcs: Dict[str, Set[int]],
    *,
    include_struct_components: bool = False,
) -> bool:
    """Return whether `name` is passed to a known array dummy parameter."""
    def contains_struct_ref(expr: c_ast.Node) -> bool:
        if isinstance(expr, c_ast.StructRef):
            return True
        return any(
            isinstance(child, c_ast.Node) and contains_struct_ref(child)
            for _key, child in expr.children()
        )

    if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID) and node.args is not None:
        array_indices = array_param_funcs.get(node.name.name, set())
        for idx, arg in enumerate(node.args.exprs):
            if idx not in array_indices:
                continue
            base = arg.expr if isinstance(arg, c_ast.UnaryOp) and arg.op == "&" else arg
            if contains_struct_ref(base) and not include_struct_components:
                continue
            if _is_dummy_target_expr(base, name):
                return True
    for _key, child in node.children():
        if isinstance(child, c_ast.Node) and is_forwarded_to_array_parameter(
            child,
            name,
            array_param_funcs,
            include_struct_components=include_struct_components,
        ):
            return True
    return False


def proc_docline(name: str, unit_kind: str) -> str:
    low = name.lower()
    if low.startswith("minmax"):
        return "compute minimum and maximum values"
    if low.startswith("mean"):
        return "compute mean value(s)"
    if low.startswith("sum"):
        return "compute sum value(s)"
    if low.startswith("read"):
        return "read values from input"
    if low.startswith("write"):
        return "write values to output"
    if low.startswith("matmul"):
        return "compute matrix product"
    if low.startswith("factor"):
        return "compute integer factors"
    if unit_kind == "function":
        return f"compute {name}"
    return f"perform {name}"


def arg_docline(name: str, ftype: str, intent: Optional[str] = None, is_array: Optional[bool] = None) -> Optional[str]:
    n = name.lower()
    if n in {"fp", "unit"}:
        return "I/O unit number"
    if n in {"n", "m", "k"}:
        return "problem size"
    if n in {"i", "j", "t"}:
        return "loop index"
    if n in {"x", "y", "z"}:
        if is_array is True:
            return "data array"
        if is_array is False:
            return "data scalar value"
        return "data value"
    if n in {"a", "b", "c"}:
        if is_array is True:
            if intent == "intent(in)":
                return "input array"
            if intent == "intent(out)":
                return "output array"
            return "input/output array"
        if is_array is False:
            if intent == "intent(in)":
                return "input scalar coefficient"
            if intent == "intent(out)":
                return "output scalar"
            if intent == "intent(inout)":
                return "input/output scalar"
            return "scalar value"
    if n in {"v"}:
        return "scalar value"
    if n in {"cap"}:
        return "allocated capacity"
    if n in {"new_cap"}:
        return "new capacity value"
    if n in {"out"}:
        return "output array"
    if "type(" in ftype.lower():
        return "derived-type argument"
    return None


def add_inline_comment(line: str, comment: Optional[str]) -> str:
    if not comment:
        return line
    code, existing = xunused.split_code_comment(line.rstrip("\r\n"))
    if existing.strip():
        return f"{code.rstrip()} {existing.lstrip()}"
    return f"{code} ! {comment}"


class Emitter:
    def __init__(
        self,
        comment_map: Optional[Dict[int, List[str]]] = None,
        line_offset: int = 0,
        array_result_funcs: Optional[Dict[str, int]] = None,
        enum_constants: Optional[Dict[str, int]] = None,
        struct_defs: Optional[Dict[str, StructDef]] = None,
        define_constants: Optional[Dict[str, Tuple[str, str]]] = None,
        generic_macros: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> None:
        self.lines: List[str] = []
        self.indent = 0
        self.arrays_1d: Set[str] = set()
        self.comment_map: Dict[int, List[str]] = comment_map or {}
        self.line_offset = line_offset
        self.comment_cursor = 1
        self.array_result_funcs: Dict[str, int] = array_result_funcs or {}
        self.enum_constants: Dict[str, int] = enum_constants or {}
        self.struct_defs: Dict[str, StructDef] = struct_defs or {}
        self.define_constants: Dict[str, Tuple[str, str]] = define_constants or {}
        self.generic_macros: Dict[str, Dict[str, str]] = generic_macros or {}
        self.array_param_funcs: Dict[str, Set[int]] = {}
        # Function name -> dummy indices written either directly or through a
        # chain of calls. Used to propagate Fortran INTENT requirements.
        self.writable_param_funcs: Dict[str, Set[int]] = {}
        # Names of scalar C strings in the current unit: indexing them uses
        # substrings and '\0' comparisons become length checks.
        self.char_string_names: Set[str] = set()
        # Per-unit identifier renames (e.g. a #define constant whose name
        # collides case-insensitively with a local in case-insensitive Fortran).
        self.id_rename: Dict[str, str] = {}
        # Name of C main's argv parameter; argv[i] lowers to argv_value(i).
        self.argv_name: Optional[str] = None
        # (function name, param index) -> module function whose interface the
        # function-pointer parameter uses, e.g. procedure(square) :: f.
        self.func_ptr_ifaces: Dict[Tuple[str, int], str] = {}
        # C pointer aliases folded away, e.g. `tmp = realloc(x, ...)` makes
        # tmp an alias of x (lowercase key -> target name).
        self.alias_map: Dict[str, str] = {}
        # Function-pointer arrays in the current unit: lowercase name -> the
        # module function providing the procedure interface.
        self.funcptr_arrays: Dict[str, str] = {}
        # Locals/dummies that are Fortran POINTERs to recursive-struct nodes.
        self.struct_ptr_names: Set[str] = set()
        self.array_result_name: Optional[str] = None
        self.array_result_tmp_alias: Optional[str] = None
        self.auto_alloc_assigned: Set[str] = set()
        self.pointer_like_names: Set[str] = set()
        self.var_infos: Dict[str, VarInfo] = {}
        self.label_map: Dict[str, int] = {}

    def _is_sizeof_node(self, n: c_ast.Node) -> bool:
        return isinstance(n, c_ast.UnaryOp) and n.op == "sizeof"

    def _mul_terms(self, n: c_ast.Node) -> List[c_ast.Node]:
        if isinstance(n, c_ast.BinaryOp) and n.op == "*":
            return self._mul_terms(n.left) + self._mul_terms(n.right)
        return [n]

    def _malloc_count_expr(self, n: c_ast.Node) -> str:
        """Extract element-count expression from malloc/realloc byte expression."""
        terms = self._mul_terms(n)
        kept = [t for t in terms if not self._is_sizeof_node(t)]
        if not kept:
            return "1"
        parts = [self.expr(t) for t in kept]
        if len(parts) == 1:
            return parts[0]
        return " * ".join(parts)

    def emit(self, line: str = "") -> None:
        self.lines.append(" " * self.indent + line)

    def simp(self, expr: str) -> str:
        # Keep generated arithmetic fully parenthesized to avoid precedence
        # changes (for example: ss/(n-1) must not become ss/n-1).
        return expr.strip()

    def cond_expr(self, n: c_ast.Node) -> str:
        """Lower a C condition to a scalar Fortran logical expression."""
        if isinstance(n, c_ast.BinaryOp) and n.op in {"&&", "||"}:
            # Recurse so integer operands (e.g. `flag && i < n`) each become
            # proper logical expressions before the .and./.or. connective.
            conn = ".and." if n.op == "&&" else ".or."
            return self.simp(f"({self.cond_expr(n.left)} {conn} {self.cond_expr(n.right)})")
        if isinstance(n, c_ast.BinaryOp) and n.op in {"==", "!=", "<", "<=", ">", ">="}:
            return self.simp(self.expr(n))
        if isinstance(n, c_ast.UnaryOp) and n.op == "!":
            return self.simp(self.expr(n))
        return self.simp(f"({self.expr(n)} /= 0)")

    @staticmethod
    def _normalize_int_literal(txt: str) -> Optional[str]:
        """Convert a C integer literal (hex/octal + u/l suffixes) to decimal."""
        m = re.match(r"^([+-]?)(0[xX][0-9a-fA-F]+|0[0-7]+|\d+)[uUlL]*$", txt.strip())
        if m is None:
            return None
        sign, body = m.group(1), m.group(2)
        try:
            if body[:2] in ("0x", "0X"):
                value = int(body, 16)
            elif len(body) > 1 and body[0] == "0":
                value = int(body, 8)
            else:
                value = int(body, 10)
        except ValueError:
            return None
        return f"{sign}{value}"

    @staticmethod
    def _decode_char_constant(token: str) -> str:
        """Translate a C character constant to a Fortran character expression."""
        try:
            value = ast.literal_eval(token)
        except (SyntaxError, ValueError):
            value = None
        if not isinstance(value, str) or len(value) != 1:
            return token
        code = ord(value)
        if value in {"\n", "\r", "\t", "\v", "\f", "\b", "\a"} or code == 0 or code > 126:
            return f"achar({code})"
        return '"' + value.replace('"', '""') + '"'

    def _init_elem_expr(self, node: c_ast.Node, real_target: bool) -> str:
        """Expr for an array initializer element, promoting ints to reals when
        the array element type is real (Fortran array constructors are typed)."""
        if real_target and isinstance(node, c_ast.Constant) and node.type == "int":
            norm = self._normalize_int_literal(node.value)
            if norm is not None:
                return f"{norm}.0_dp"
        return self.expr(node)

    @staticmethod
    def _is_nul_char_constant(node: c_ast.Node) -> bool:
        if not (isinstance(node, c_ast.Constant) and node.type == "char"):
            return False
        try:
            value = ast.literal_eval(node.value)
        except (SyntaxError, ValueError):
            return False
        return isinstance(value, str) and len(value) == 1 and ord(value) == 0

    def _nul_terminator_compare(self, n: c_ast.BinaryOp) -> Optional[str]:
        """Rewrite `s[i] != '\\0'` (or ==) as an index-vs-length test."""
        for ref, nul in ((n.left, n.right), (n.right, n.left)):
            if not self._is_nul_char_constant(nul):
                continue
            if not (
                isinstance(ref, c_ast.ArrayRef)
                and isinstance(ref.name, c_ast.ID)
                and ref.name.name.lower() in self.char_string_names
            ):
                continue
            base = ref.name.name
            idx = self.expr(ref.subscript)
            if n.op == "!=":
                return f"(({idx}) < len_trim({base}))"
            return f"(({idx}) >= len_trim({base}))"
        return None

    def _lower_call_args(self, fname: str, arg_nodes: List[c_ast.Node]) -> List[str]:
        """Lower call arguments, turning `&arr[i]` into an array section when the
        callee's corresponding parameter is an array (C array decay)."""
        arr_idxs = self.array_param_funcs.get(fname, set())
        out: List[str] = []
        for idx, a in enumerate(arg_nodes):
            if idx in arr_idxs and isinstance(a, c_ast.UnaryOp) and a.op == "&" and isinstance(a.expr, c_ast.ArrayRef):
                base = self.expr(a.expr.name)
                off = self.expr(a.expr.subscript)
                out.append(base if off.strip() in ("0", "+0") else f"{base}(({off})+1:)")
            else:
                out.append(self.expr(a))
        return out

    def _rename_ids_in_text(self, txt: str) -> str:
        """Apply per-unit identifier renames to already-rendered text."""
        for old, new in self.id_rename.items():
            txt = re.sub(rf"\b{re.escape(old)}\b", new, txt)
        return txt

    def _flex_member_for(self, var_name: Optional[str]) -> Optional[str]:
        """Flexible-array-member name when var is a struct that carries one."""
        if not var_name:
            return None
        info = self.var_infos.get(var_name.lower())
        if info is None:
            return None
        m = re.match(r"^type\(([^)]+)\)$", info.ftype, re.IGNORECASE)
        if m is None:
            return None
        return _STRUCT_FLEX_MEMBERS.get(m.group(1).lower())

    def _is_pointer_like_id(self, n: c_ast.Node) -> bool:
        return isinstance(n, c_ast.ID) and n.name.lower() in self.pointer_like_names

    def _is_repeatable_term(self, n: c_ast.Node) -> bool:
        """True when term can be safely duplicated (no side effects)."""
        return isinstance(n, (c_ast.ID, c_ast.ArrayRef, c_ast.StructRef, c_ast.Constant))

    def emit_comments_to(self, src_line: int) -> None:
        """Emit preserved comments up to and including source line."""
        if src_line < self.comment_cursor:
            return
        for ln in range(self.comment_cursor, src_line + 1):
            for c in self.comment_map.get(ln, []):
                self.emit(f"! {c}")
        self.comment_cursor = src_line + 1

    def emit_leading_comments_before(self, src_line: int, *, window: int = 40) -> None:
        """Emit nearby leading comments (before signature) immediately after signature."""
        for c in self.pop_leading_comments_before(src_line, window=window):
            self.emit(f"! {c}")
        if self.comment_cursor <= src_line:
            self.comment_cursor = src_line + 1

    def pop_leading_comments_before(self, src_line: int, *, window: int = 12) -> List[str]:
        """Collect and remove nearby leading comments (before signature).

        Only keeps the nearest contiguous comment cluster before `src_line`
        to avoid pulling comments from prior procedures.
        """
        lo = max(1, src_line - window)
        lines_with_comments = [ln for ln in range(lo, src_line + 1) if self.comment_map.get(ln)]
        if not lines_with_comments:
            return []
        # Keep only the last contiguous cluster.
        cluster: List[int] = [lines_with_comments[-1]]
        for ln in reversed(lines_with_comments[:-1]):
            if cluster[0] - ln <= 1:
                cluster.insert(0, ln)
            else:
                break
        pending: List[str] = []
        for ln in cluster:
            vals = self.comment_map.get(ln, [])
            if vals:
                pending.extend(vals)
                self.comment_map[ln] = []
        return pending

    def expr(self, n: c_ast.Node) -> str:
        if isinstance(n, c_ast.Constant):
            if n.type == "string":
                return n.value
            if n.type == "char":
                return self._decode_char_constant(n.value)
            txt = n.value
            if n.type == "int" or re.match(r"^[+-]?\d", txt):
                normalized = self._normalize_int_literal(txt)
                if normalized is not None:
                    return normalized
            # Normalize C float suffixes (e.g. 0.0f, 1e-3F) to Fortran-real literals.
            txt = re.sub(r"(?i)^([+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[e][+-]?\d+)?)f$", r"\1", txt)
            return txt
        if isinstance(n, c_ast.ID):
            if n.name == "NULL":
                return "0"
            if n.name == "RAND_MAX":
                return "2147483647"
            if n.name == "EXIT_SUCCESS":
                return "0"
            if n.name == "EXIT_FAILURE":
                return "1"
            if n.name in _C_LIMIT_CONSTANTS:
                return _C_LIMIT_CONSTANTS[n.name]
            if n.name == "stderr":
                return "0"
            if n.name == "stdout":
                return "6"
            if n.name == "stdin":
                return "5"
            if n.name == "NAN":
                return "ieee_value(0.0_dp, ieee_quiet_nan)"
            if n.name in {"INFINITY", "HUGE_VAL"}:
                return "ieee_value(0.0_dp, ieee_positive_inf)"
            if n.name == "I":
                return "(0.0_dp, 1.0_dp)"
            if self.array_result_name is not None and self.array_result_tmp_alias is not None:
                if n.name == self.array_result_tmp_alias:
                    return self.array_result_name
            if n.name.lower() in self.alias_map:
                return self.alias_map[n.name.lower()]
            return self.id_rename.get(n.name, n.name)
        if isinstance(n, c_ast.Cast):
            target, _ = c_to_ftype(n.to_type)
            inner = self.expr(n.expr)
            tl = target.lower()
            if tl.startswith("integer"):
                return self.simp(f"int({inner})")
            if tl.startswith("real"):
                mk = re.search(r"kind\s*=\s*([a-z_]\w*)", tl)
                kname = mk.group(1) if mk else "dp"
                return self.simp(f"real({inner}, kind={kname})")
            return inner
        if isinstance(n, c_ast.UnaryOp):
            op = n.op
            if op == "sizeof":
                # Size information is typically consumed in malloc/realloc byte counts.
                # Keep lowering conservative for now.
                return "1"
            if op == "&":
                return self.expr(n.expr)
            if op == "*":
                # Explicit dereference of pointer arithmetic reads a single
                # element: *(p + i) -> p((i)+1).
                inner = n.expr
                if isinstance(inner, c_ast.BinaryOp) and inner.op == "+":
                    if self._is_pointer_like_id(inner.left):
                        return f"{self.expr(inner.left)}(({self.expr(inner.right)})+1)"
                    if self._is_pointer_like_id(inner.right):
                        return f"{self.expr(inner.right)}(({self.expr(inner.left)})+1)"
                return self.expr(n.expr)
            if op == "p++" or op == "p--":
                return self.expr(n.expr)
            if op == "-":
                return self.simp(f"-({self.expr(n.expr)})")
            if op == "+":
                return self.simp(f"+({self.expr(n.expr)})")
            if op == "!":
                if self._is_alloc_entity(n.expr):
                    return f"(.not. allocated({self.expr(n.expr)}))"
                if isinstance(n.expr, c_ast.ID):
                    return self.simp(f"({self.expr(n.expr)} == 0)")
                if (
                    isinstance(n.expr, c_ast.FuncCall)
                    and isinstance(n.expr.name, c_ast.ID)
                    and n.expr.name.name == "isfinite"
                ):
                    return self.simp(f".not. ({self.expr(n.expr)})")
                if isinstance(n.expr, c_ast.BinaryOp) and n.expr.op in {
                    "==", "!=", "<", "<=", ">", ">=", "&&", "||"
                }:
                    return self.simp(f".not. ({self.cond_expr(n.expr)})")
                # C functions and arithmetic expressions are numeric truth
                # values; Fortran's .not. accepts only LOGICAL operands.
                return self.simp(f"({self.expr(n.expr)} == 0)")
            if op == "~":
                return self.simp(f"not({self.expr(n.expr)})")
        if isinstance(n, c_ast.BinaryOp):
            op = n.op
            # `s[i] != '\0'` / `s[i] == '\0'` on a C string: in the exact-length
            # Fortran model there is no terminator, so test the index bound.
            if op in ("==", "!="):
                nul_cmp = self._nul_terminator_compare(n)
                if nul_cmp is not None:
                    return nul_cmp
                # NULL tests on POINTER entities become association tests.
                for side, other in ((n.left, n.right), (n.right, n.left)):
                    if isinstance(other, c_ast.ID) and other.name == "NULL" and self._is_ptr_entity(side):
                        base = self.expr(side)
                        if op == "==":
                            return f"(.not. associated({base}))"
                        return f"associated({base})"
                    if isinstance(other, c_ast.ID) and other.name == "NULL" and self._is_alloc_entity(side):
                        base = self.expr(side)
                        if op == "==":
                            return f"(.not. allocated({base}))"
                        return f"allocated({base})"
            # C pointer arithmetic used as "tail pointer" argument: a + k
            if op == "+":
                if self._is_pointer_like_id(n.left):
                    base = self.expr(n.left)
                    off = self.expr(n.right)
                    if off.strip() in {"0", "+0", "0L", "0l"}:
                        return base
                    return f"{base}(({off})+1:)"
                if self._is_pointer_like_id(n.right):
                    base = self.expr(n.right)
                    off = self.expr(n.left)
                    if off.strip() in {"0", "+0", "0L", "0l"}:
                        return base
                    return f"{base}(({off})+1:)"
            op_map = {
                "&&": ".and.",
                "||": ".or.",
                "==": "==",
                "!=": "/=",
                "<": "<",
                "<=": "<=",
                ">": ">",
                ">=": ">=",
                "+": "+",
                "-": "-",
                "*": "*",
                "/": "/",
                "%": "mod",
            }
            if op == "*" and self._is_repeatable_term(n.left) and self._is_repeatable_term(n.right):
                ltxt = self.expr(n.left)
                rtxt = self.expr(n.right)
                if re.sub(r"\s+", "", ltxt).lower() == re.sub(r"\s+", "", rtxt).lower():
                    return self.simp(f"({ltxt}**2)")
            if op == "%":
                return self.simp(f"mod({self.expr(n.left)}, {self.expr(n.right)})")
            # C bitwise operators map to Fortran bit intrinsics.
            if op == "&":
                return self.simp(f"iand({self.expr(n.left)}, {self.expr(n.right)})")
            if op == "|":
                return self.simp(f"ior({self.expr(n.left)}, {self.expr(n.right)})")
            if op == "^":
                return self.simp(f"ieor({self.expr(n.left)}, {self.expr(n.right)})")
            if op == "<<":
                return self.simp(f"ishft({self.expr(n.left)}, {self.expr(n.right)})")
            if op == ">>":
                return self.simp(f"ishft({self.expr(n.left)}, -({self.expr(n.right)}))")
            return self.simp(f"({self.expr(n.left)} {op_map.get(op, op)} {self.expr(n.right)})")
        if isinstance(n, c_ast.InitList):
            vals = n.exprs or []
            return "[" + ", ".join(self.expr(v) for v in vals) + "]"
        if isinstance(n, c_ast.TernaryOp):
            t_expr, f_expr = self._pad_char_literals(self.expr(n.iftrue), self.expr(n.iffalse))
            return f"merge({t_expr}, {f_expr}, {self.cond_expr(n.cond)})"
        if isinstance(n, c_ast.ArrayRef):
            # argv[i] -> command-line argument i (positions align: both models
            # use 0 for the command name).
            if (
                self.argv_name is not None
                and isinstance(n.name, c_ast.ID)
                and n.name.name.lower() == self.argv_name
            ):
                return f"argv_value({self.expr(n.subscript)})"
            # Indexing a scalar C string reads one character: use a substring.
            if isinstance(n.name, c_ast.ID) and n.name.name.lower() in self.char_string_names:
                base = n.name.name
                idx_txt = self.expr(n.subscript)
                return f"{base}(({idx_txt})+1:({idx_txt})+1)"
            # C multidimensional arrays are row-major. Reverse both dimensions
            # and subscripts in Fortran so a flat initializer retains its order.
            indices: List[c_ast.Node] = []
            base_node: c_ast.Node = n
            while isinstance(base_node, c_ast.ArrayRef):
                indices.append(base_node.subscript)
                base_node = base_node.name
            if len(indices) > 1:
                base = self.expr(base_node)
                rendered = [f"{self.expr(index)}+1" for index in indices]
                return f"{base}({', '.join(rendered)})"
            idx = n.subscript
            # C pointer indexing: (a + off)[i] => a(off + i + 1)
            if isinstance(n.name, c_ast.BinaryOp) and n.name.op == "+":
                if self._is_pointer_like_id(n.name.left):
                    base = self.expr(n.name.left)
                    off = self.expr(n.name.right)
                    iexpr = self.expr(idx)
                    return f"{base}(({off}) + ({iexpr})+1)"
                if self._is_pointer_like_id(n.name.right):
                    base = self.expr(n.name.right)
                    off = self.expr(n.name.left)
                    iexpr = self.expr(idx)
                    return f"{base}(({off}) + ({iexpr})+1)"
            name = self.expr(n.name)
            if isinstance(idx, c_ast.UnaryOp) and idx.op == "p++":
                return f"{name}({self.expr(idx.expr)}+1)"
            return f"{name}({self.expr(idx)}+1)"
        if isinstance(n, c_ast.FuncCall):
            # ops[i](args): call through a function-pointer array element.
            if (
                isinstance(n.name, c_ast.ArrayRef)
                and isinstance(n.name.name, c_ast.ID)
                and n.name.name.name.lower() in self.funcptr_arrays
            ):
                base = self.expr(n.name)
                args = [self.expr(a) for a in (n.args.exprs if n.args is not None else [])]
                return f"{base}%fp({', '.join(args)})"
            fname = self.expr(n.name)
            # `&arr[i]` (array decay) passed where the callee expects an array
            # becomes an array section `arr(i+1:)` rather than a scalar element.
            if isinstance(n.name, c_ast.ID) and n.name.name in self.array_param_funcs and n.args is not None:
                lowered = self._lower_call_args(n.name.name, n.args.exprs)
                return f"{n.name.name}({', '.join(lowered)})"
            # _Generic type-selection macro: pick the branch for the argument's
            # static type at translation time.
            if isinstance(n.name, c_ast.ID) and n.name.name.lower() in self.generic_macros:
                mapping = self.generic_macros[n.name.name.lower()]
                if n.args is not None and len(n.args.exprs) == 1:
                    ctype = self._arg_c_type(n.args.exprs[0])
                    result = mapping.get(ctype or "", None) or mapping.get("default")
                    if result is not None:
                        return result
            args = []
            if n.args is not None:
                args = [self.expr(a) for a in n.args.exprs]
            if fname in {"fabs", "fabsf", "fabsl"} and len(args) >= 1:
                return self.simp(f"abs({args[0]})")
            if fname == "isfinite" and len(args) == 1:
                return f"ieee_is_finite({args[0]})"
            if fname == "strlen" and len(args) == 1:
                return self.simp(f"len_trim({args[0]})")
            if fname == "strcmp" and len(args) == 2:
                a0, a1 = args
                return self.simp(f"merge(-1, merge(1, 0, {a0} > {a1}), {a0} < {a1})")
            if fname in {"fminf", "fmin"} and len(args) >= 2:
                return self.simp(f"min({args[0]}, {args[1]})")
            if fname in {"fmaxf", "fmax"} and len(args) >= 2:
                return self.simp(f"max({args[0]}, {args[1]})")
            if fname == "sqrt":
                a0 = args[0]
                if re.match(r"^\s*real\s*\(", a0, re.IGNORECASE):
                    return self.simp(f"sqrt({a0})")
                return self.simp(f"sqrt(real({a0}, kind=dp))")
            if fname == "floor":
                return self.simp(f"floor({args[0]})")
            if fname in {"pow", "powf", "powl"} and len(args) >= 2:
                return self.simp(f"({args[0]})**({args[1]})")
            if fname == "creal":
                return self.simp(f"real({args[0]}, kind=dp)")
            if fname == "cimag":
                return self.simp(f"aimag({args[0]})")
            if fname == "printf":
                return "__PRINTF__"
            if fname in self.array_result_funcs:
                out_idx = self.array_result_funcs[fname]
                if 0 <= out_idx < len(args):
                    args = [a for i, a in enumerate(args) if i != out_idx]
            return f"{fname}({', '.join(args)})"
        if isinstance(n, c_ast.StructRef):
            base = self.expr(n.name)
            field = self.expr(n.field)
            return f"{base}%{field}"
        if isinstance(n, c_ast.CompoundLiteral):
            tnode = n.type.type if isinstance(n.type, c_ast.Typename) else n.type
            ftype, _ = c_to_ftype(tnode)
            m = re.match(r"^type\(([^)]+)\)$", ftype, re.IGNORECASE)
            if m is not None and isinstance(n.init, c_ast.InitList):
                return self._struct_constructor(m.group(1), n.init)
            if isinstance(n.init, c_ast.InitList):
                return self.expr(n.init)
        raise NotImplementedError(f"Unsupported expr: {type(n).__name__}")

    @staticmethod
    def _printf_edit_descriptor(conv: str, width: str, prec: str) -> Optional[str]:
        """Map a single C printf conversion to a Fortran edit descriptor."""
        w = width if (width and width != "*") else ""
        p = prec if (prec and prec != "*") else ""
        c = conv.lower()
        if c in ("d", "i", "u"):
            return f"i{w}" if w else "i0"
        if c == "x":
            return f"z{w}" if w else "z0"
        if c == "o":
            return f"o{w}" if w else "o0"
        if c == "f":
            pp = p or "6"
            return f"f{w}.{pp}" if w else f"f0.{pp}"
        if c == "e":
            pp = p or "6"
            return f"es{w}.{pp}" if w else f"es0.{pp}"
        if c == "g":
            pp = p or "6"
            return f"g{w}.{pp}" if w else "g0"
        if c == "a":  # C hexadecimal float; approximate.
            pp = p or "6"
            return f"es{w}.{pp}" if w else f"es0.{pp}"
        if c == "s":
            return f"a{w}" if w else "a"
        if c == "c":
            return "a1"
        return None

    _PRINTF_CONV_RE = re.compile(
        r"%([-+ 0#]*)(\d+|\*)?(?:\.(\d+|\*))?(?:hh|h|ll|l|j|z|t|L)*([diouxXeEfFgGaAcs%])"
    )

    def _translate_printf(
        self,
        fmt_literal: str,
        vals: List[c_ast.Node],
        *,
        unit: str = "*",
        internal: bool = False,
    ) -> Optional[List[str]]:
        """Translate a C printf format + arguments to a Fortran write statement.

        Returns the emitted line(s), or ``None`` if the format cannot be
        represented (so the caller can fall back). Literal text (labels) is
        preserved and each conversion becomes a separate edit descriptor, so
        fields never run together. With ``internal=True`` the write targets a
        character variable (sprintf) where advance= is not allowed.
        """
        text = _decode_c_string_literal(fmt_literal)
        if text is None:
            return None
        advance = True
        if text.endswith("\n"):
            text = text[:-1]
        elif not internal:
            advance = False

        fmt_items: List[str] = []
        arg_exprs: List[str] = []
        lit: List[str] = []

        def flush_lit() -> None:
            if lit:
                fmt_items.append('"' + "".join(lit).replace('"', '""') + '"')
                lit.clear()

        i = 0
        vi = 0
        while i < len(text):
            ch = text[i]
            if ch == "\n":
                flush_lit()
                fmt_items.append("/")
                i += 1
                continue
            if ch == "%":
                m = self._PRINTF_CONV_RE.match(text, i)
                if m is None:
                    lit.append(ch)
                    i += 1
                    continue
                flags, width, prec, conv = m.groups()
                i = m.end()
                if conv == "%":
                    lit.append("%")
                    continue
                if vi >= len(vals):
                    return None
                desc = self._printf_edit_descriptor(conv, width or "", prec or "")
                if desc is None:
                    return None
                flush_lit()
                fmt_items.append(desc)
                arg_txt = self.expr(vals[vi])
                # %s: trim trailing blanks that fixed-length or padded Fortran
                # strings carry; exact-length strings are unaffected.
                if conv == "s" and not re.match(r'^".*"$', arg_txt, re.DOTALL):
                    arg_txt = f"trim({arg_txt})"
                arg_exprs.append(arg_txt)
                vi += 1
                continue
            lit.append(ch)
            i += 1
        flush_lit()

        if vi != len(vals):
            return None  # argument count mismatch; let caller fall back.

        adv = "" if (advance or internal) else ', advance="no"'
        if not fmt_items:
            # Pure newline (or empty) format: emit a blank record.
            return [f"write({unit},*)"] if advance else []
        fmt = "'(" + ", ".join(fmt_items) + ")'"
        if arg_exprs:
            return [f"write({unit}, {fmt}{adv}) {', '.join(arg_exprs)}"]
        return [f"write({unit}, {fmt}{adv})"]

    def emit_printf(self, fc: c_ast.FuncCall) -> bool:
        args = fc.args.exprs if fc.args is not None else []
        if not args:
            self.emit(_xc2f_added_comment("approximated printf format"))
            self.emit("write(*,*)")
            return True
        fmt_node = args[0]
        if not isinstance(fmt_node, c_ast.Constant) or fmt_node.type != "string":
            self.emit(_xc2f_added_comment("approximated printf format"))
            self.emit(f"write(*,*) {', '.join(self.expr(a) for a in args)}")
            return True
        vals = args[1:]
        if not vals:
            text = _decode_c_string_literal(fmt_node.value)
            text = _literal_printf_text(text) if text is not None else None
            if text is not None:
                ends_record = text.endswith("\n")
                if ends_record:
                    text = text[:-1]
                value = _fortran_character_expr(text)
                if ends_record:
                    self.emit(f'write(*,"(a)") {value}')
                else:
                    self.emit(f'write(*,"(a)", advance="no") {value}')
                return True
        fmt = fmt_node.value.strip('"')
        if fmt == "%d:" and len(vals) == 1:
            self.emit(f'write(*,"(i0,a)", advance="no") {self.expr(vals[0])}, ":"')
            return True
        if fmt == " %d" and len(vals) == 1:
            self.emit(f'write(*,"(a,i0)", advance="no") " ", {self.expr(vals[0])}')
            return True
        if fmt == "\\n":
            self.emit("write(*,*)")
            return True
        if fmt in ("%g\\n", "%f\\n", "%lf\\n") and len(vals) == 1:
            self.emit(f"write(*,*) {self.expr(vals[0])}")
            return True
        if fmt == "min=%g max=%g\\n" and len(vals) == 2:
            self.emit(f'write(*,\'("min=",g0," max=",g0)\') {self.expr(vals[0])}, {self.expr(vals[1])}')
            return True
        # General translation: preserve literal labels and keep each field as a
        # separate edit descriptor so outputs never run together.
        translated = self._translate_printf(fmt_node.value, vals)
        if translated is not None:
            for line in translated:
                self.emit(line)
            return True

        # Fallback for unsupported formats: preserve data output list-directed.
        self.emit(_xc2f_added_comment(f'approximated printf format: "{fmt}"'))
        if vals:
            self.emit(f"write(*,*) {', '.join(self.expr(v) for v in vals)}")
        else:
            self.emit("write(*,*)")
        return False

    def emit_decl(self, name: str, info: VarInfo, params: Set[str], ret_name: Optional[str]) -> None:
        if name in params:
            return
        if ret_name is not None and name == ret_name:
            return
        if info.char_string and not info.shape:
            # Scalar C string: deferred-length allocatable (exact value) or a
            # fixed-length buffer; never a rank-1 array.
            if info.alloc:
                self.emit(f"{info.ftype}, allocatable :: {name}")
            else:
                self.emit(f"{info.ftype} :: {name}")
            return
        if info.struct_ptr:
            self.emit(f"{info.ftype}, pointer :: {name}")
            return
        # A by-value local of a recursive struct type may have its address
        # linked into other nodes: give it the TARGET attribute.
        mrec = re.match(r"^type\(([^)]+)\)$", info.ftype, re.IGNORECASE)
        if mrec is not None and mrec.group(1).lower() in _STRUCT_RECURSIVE and not info.shape and not info.alloc:
            self.emit(f"{info.ftype}, target :: {name}")
            return
        if info.alloc:
            self.emit(f"{info.ftype}, allocatable :: {name}(:)")
            self.arrays_1d.add(name)
        elif info.shape:
            dims = self._rename_ids_in_text(", ".join(info.shape))
            self.emit(f"{info.ftype} :: {name}({dims})")
        else:
            self.emit(f"{info.ftype} :: {name}")

    def _flatten_init_list(self, init: c_ast.InitList) -> List[c_ast.Node]:
        values: List[c_ast.Node] = []
        for item in init.exprs or []:
            if isinstance(item, c_ast.InitList):
                values.extend(self._flatten_init_list(item))
            else:
                values.append(item)
        return values

    def emit_decl_grouped(self, decls: Dict[str, VarInfo], params: Set[str], ret_name: Optional[str]) -> None:
        """Emit declarations with non-allocatable entities first, then allocatables."""
        items = [(n, info) for n, info in decls.items() if n not in params and not (ret_name is not None and n == ret_name)]
        type_order = {"integer": 0, "logical": 1, "real(kind=sp)": 2, "real(kind=dp)": 3, "real(kind=real64)": 3, "character": 4}
        items.sort(key=lambda x: (1 if x[1].alloc else 0, type_order.get(x[1].ftype.lower(), 50), x[0].lower()))
        for n, info in items:
            self.emit_decl(n, info, params=params, ret_name=ret_name)

    def _emit_for_init(self, init: Optional[c_ast.Node]) -> None:
        """Emit the initialization part of a C for-loop as standalone statements."""
        if init is None:
            return
        if isinstance(init, c_ast.Assignment):
            self.emit_assignment(init)
            return
        if isinstance(init, c_ast.DeclList):
            for decl in init.decls or []:
                if isinstance(decl, c_ast.Decl) and decl.init is not None:
                    self.emit(f"{decl.name} = {self.expr(decl.init)}")
            return
        raise NotImplementedError("Unsupported for init")

    def _stmt_contains_continue(self, node: Optional[c_ast.Node]) -> bool:
        """Return True when subtree contains a C continue statement."""
        if node is None:
            return False
        if isinstance(node, c_ast.Continue):
            return True
        for _name, child in node.children():
            if isinstance(child, c_ast.Node) and self._stmt_contains_continue(child):
                return True
        return False

    def emit_for(
        self,
        st: c_ast.For,
        *,
        ret_name: Optional[str] = None,
        array_result_name: Optional[str] = None,
    ) -> None:
        # Infinite loop: for(;;) { ... }
        if st.init is None and st.cond is None and st.next is None:
            self.emit("do")
            self.indent += 3
            self.emit_stmt(st.stmt, ret_name=ret_name, array_result_name=array_result_name)
            self.indent -= 3
            self.emit("end do")
            return

        if isinstance(st.init, c_ast.Assignment):
            var = self.expr(st.init.lvalue)
            lb = self.expr(st.init.rvalue)
        elif isinstance(st.init, c_ast.DeclList) and len(st.init.decls) == 1:
            d = st.init.decls[0]
            var = d.name
            lb = self.expr(d.init)
        else:
            raise NotImplementedError("Unsupported for init")

        var_l = var.strip().lower()

        simple_cond = False
        cond_op = ""
        bound_expr = ""
        if isinstance(st.cond, c_ast.BinaryOp):
            # Normalize C loop condition so either `i < ub` or reversed `lb <= i` work.
            cond_op = st.cond.op
            if isinstance(st.cond.left, c_ast.ID) and self.expr(st.cond.left).strip().lower() == var_l:
                bound_expr = self.expr(st.cond.right)
                simple_cond = True
            elif isinstance(st.cond.right, c_ast.ID) and self.expr(st.cond.right).strip().lower() == var_l:
                bound_expr = self.expr(st.cond.left)
                invert = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}
                if cond_op in invert:
                    cond_op = invert[cond_op]
                    simple_cond = True
                else:
                    raise NotImplementedError("Unsupported for condition operator")

        if not simple_cond:
            if st.cond is None:
                self._emit_for_init(st.init)
                self.emit("do")
                self.indent += 3
                self.emit_stmt(st.stmt, ret_name=ret_name, array_result_name=array_result_name)
                if st.next is not None:
                    self.emit_stmt(st.next, ret_name=ret_name, array_result_name=array_result_name)
                self.indent -= 3
                self.emit("end do")
                return
            if self._stmt_contains_continue(st.stmt):
                raise NotImplementedError("Only simple for cond supported")
            self._emit_for_init(st.init)
            self.emit(f"do while ({self.cond_expr(st.cond)})")
            self.indent += 3
            self.emit_stmt(st.stmt, ret_name=ret_name, array_result_name=array_result_name)
            if st.next is not None:
                self.emit_stmt(st.next, ret_name=ret_name, array_result_name=array_result_name)
            self.indent -= 3
            self.emit("end do")
            return

        ub = bound_expr
        step = None
        if cond_op in ("<", ">"):
            if cond_op == "<":
                ub = f"({ub})-1"
            else:
                ub = f"({ub})+1"

        def _const_int_text(n: c_ast.Node) -> Optional[str]:
            if isinstance(n, c_ast.Constant):
                txt = n.value.strip()
                if re.match(r"^[+-]?\d+$", txt):
                    return txt
            return None

        def _same_var(n: c_ast.Node) -> bool:
            return isinstance(n, c_ast.ID) and self.expr(n).strip().lower() == var_l

        if isinstance(st.next, c_ast.UnaryOp) and st.next.op in ("p++", "++"):
            step = None
        elif isinstance(st.next, c_ast.UnaryOp) and st.next.op in ("p--", "--"):
            step = "-1"
        elif isinstance(st.next, c_ast.Assignment) and isinstance(st.next.lvalue, c_ast.ID) and self.expr(st.next.lvalue).strip().lower() == var_l:
            # += / -= forms
            if st.next.op in ("+=", "-="):
                c = _const_int_text(st.next.rvalue)
                if c is not None:
                    if st.next.op == "+=":
                        step = None if c == "1" else c
                    else:
                        step = "-1" if c == "1" else f"-({c})"
                else:
                    # non-constant step expression
                    rhs = self.expr(st.next.rvalue)
                    step = rhs if st.next.op == "+=" else f"-({rhs})"
            elif st.next.op == "=" and isinstance(st.next.rvalue, c_ast.BinaryOp) and st.next.rvalue.op in ("+", "-"):
                # i = i +/- c, i = c + i
                bop = st.next.rvalue.op
                l, r = st.next.rvalue.left, st.next.rvalue.right
                if _same_var(l):
                    c = _const_int_text(r)
                    if c is not None:
                        if bop == "+":
                            step = None if c == "1" else c
                        else:
                            step = "-1" if c == "1" else f"-({c})"
                    else:
                        rr = self.expr(r)
                        step = rr if bop == "+" else f"-({rr})"
                elif bop == "+" and _same_var(r):
                    c = _const_int_text(l)
                    if c is not None:
                        step = None if c == "1" else c
                    else:
                        step = self.expr(l)
                else:
                    raise NotImplementedError("Unsupported for step")
            else:
                raise NotImplementedError("Unsupported for step")
        else:
            raise NotImplementedError("Unsupported for step")

        if step is None:
            self.emit(f"do {var} = {lb}, {ub}")
        else:
            self.emit(f"do {var} = {lb}, {ub}, {step}")
        self.indent += 3
        self.emit_stmt(st.stmt, ret_name=ret_name, array_result_name=array_result_name)
        self.indent -= 3
        self.emit("end do")

    def _emit_incdec_value(self, target: str, u: c_ast.UnaryOp) -> None:
        """Emit ``target = x++`` / ``++x`` style increment/decrement as a value."""
        v = self.expr(u.expr)
        step = "+ 1" if u.op in ("p++", "++") else "- 1"
        if u.op in ("p++", "p--"):  # postfix: value is the old contents
            self.emit(f"{target} = {v}")
            self.emit(f"{v} = {v} {step}")
        else:  # prefix: value is the updated contents
            self.emit(f"{v} = {v} {step}")
            self.emit(f"{target} = {v}")

    @staticmethod
    def _ftype_to_c_type(ftype: str) -> Optional[str]:
        """Map a Fortran type back to the C type name used in _Generic macros."""
        t = ftype.lower()
        if t.startswith("integer"):
            return "int"
        if "kind=sp" in t:
            return "float"
        if "kind=dp" in t or "real64" in t or t.startswith("real"):
            return "double"
        return None

    def _arg_c_type(self, arg: c_ast.Node) -> Optional[str]:
        """Best-effort C type of an argument for _Generic resolution."""
        if isinstance(arg, c_ast.ID):
            info = self.var_infos.get(arg.name.lower())
            if info is not None:
                return self._ftype_to_c_type(info.ftype)
        if isinstance(arg, c_ast.Constant):
            if arg.type in ("int", "long", "unsigned int", "long long"):
                return "int"
            if arg.type in ("double", "float"):
                return "double"
        return None

    @staticmethod
    def _pad_char_literals(a: str, b: str) -> Tuple[str, str]:
        """Pad two Fortran character literals to equal length for `merge`."""
        ma = re.match(r'^"(.*)"$', a, re.DOTALL)
        mb = re.match(r'^"(.*)"$', b, re.DOTALL)
        if ma is not None and mb is not None:
            width = max(len(ma.group(1)), len(mb.group(1)))
            return f'"{ma.group(1).ljust(width)}"', f'"{mb.group(1).ljust(width)}"'
        return a, b

    @staticmethod
    def _zero_literal(ftype: str) -> str:
        t = ftype.lower()
        if t.startswith("integer"):
            return "0"
        if t.startswith("complex"):
            return "(0.0_dp, 0.0_dp)"
        if t.startswith("real"):
            return "0.0_dp"
        if t.startswith("logical"):
            return ".false."
        return "0"

    def _component_value(self, node: c_ast.Node, ftype: str, shape: Optional[str] = None) -> str:
        """Lower one struct-component initializer, recursing into nested structs
        and array-valued components."""
        if shape == "*":
            # Pointer component: NULL -> null(), &var -> the TARGET variable.
            if isinstance(node, c_ast.ID) and node.name == "NULL":
                return "null()"
            if isinstance(node, c_ast.UnaryOp) and node.op == "&":
                return self.expr(node.expr)
        m = re.match(r"^type\(([^)]+)\)$", ftype, re.IGNORECASE)
        if m is not None and isinstance(node, c_ast.InitList) and m.group(1).lower() in self.struct_defs:
            return self._struct_constructor(m.group(1), node)
        real_target = ftype.lower().startswith("real")
        if isinstance(node, c_ast.InitList):
            vals = ", ".join(self._init_elem_expr(x, real_target) for x in self._flatten_init_list(node))
            return f"[{vals}]"
        return self._init_elem_expr(node, real_target)

    def _struct_constructor(self, type_name: str, init: c_ast.InitList) -> str:
        """Build a Fortran structure constructor from a C struct initializer.

        Handles positional (`{1, 2}`) and designated (`{.a = 1}`) forms, plus
        nested struct and array-valued components; omitted designated fields are
        filled with a type-appropriate zero.
        """
        exprs = init.exprs or []
        sdef = self.struct_defs.get(type_name.lower())
        if sdef is None:
            values = ", ".join(self.expr(v) for v in exprs)
            return f"{type_name}({values})"
        if any(isinstance(e, c_ast.NamedInitializer) for e in exprs):
            field_vals: Dict[str, str] = {}
            spec_by_name = {fn.lower(): (ft, sh) for fn, ft, sh in sdef.fields}
            for e in exprs:
                if isinstance(e, c_ast.NamedInitializer) and e.name and isinstance(e.name[0], c_ast.ID):
                    fn = e.name[0].name.lower()
                    ft, sh = spec_by_name.get(fn, ("integer", None))
                    field_vals[fn] = self._component_value(e.expr, ft, sh)
            ordered = [
                field_vals.get(fname.lower(), "null()" if shape == "*" else self._zero_literal(ftype))
                for fname, ftype, shape in sdef.fields
            ]
        else:
            ordered = [
                self._component_value(v, ftype, shape)
                for (fname, ftype, shape), v in zip(sdef.fields, exprs)
            ]
        return f"{type_name}({', '.join(ordered)})"

    def _is_ptr_entity(self, node: c_ast.Node) -> bool:
        """True when the expression denotes a Fortran POINTER entity."""
        if isinstance(node, c_ast.ID):
            return node.name.lower() in self.struct_ptr_names
        if isinstance(node, c_ast.StructRef) and isinstance(node.field, c_ast.ID):
            fname = node.field.name.lower()
            return any(fname in flds for flds in _STRUCT_PTR_FIELDS.values())
        return False

    def _is_alloc_entity(self, node: c_ast.Node) -> bool:
        """True when an expression denotes a lowered allocatable entity."""
        if isinstance(node, c_ast.ID):
            info = self.var_infos.get(node.name.lower())
            return info is not None and info.alloc
        if isinstance(node, c_ast.StructRef) and isinstance(node.field, c_ast.ID):
            fname = node.field.name.lower()
            return any(fname in fields for fields in _STRUCT_ALLOC_FIELDS.values())
        return False

    def _mask_unsigned(self, lhs: str, rhs: str) -> str:
        """Mask assignments to unsigned 32-bit targets to C wraparound."""
        vinfo = self.var_infos.get(lhs.lower())
        if vinfo is not None and vinfo.unsigned:
            return f"iand({rhs}, 4294967295_int64)"
        return rhs

    def _emit_realloc_grow(self, lhs: str, fc: c_ast.FuncCall) -> None:
        """Emit allocatable growth (move_alloc) for a C realloc of `lhs`."""
        size_arg = fc.args.exprs[1]
        n = self._malloc_count_expr(size_arg)
        vinfo = self.var_infos.get(lhs.lower())
        tmp_name = f"{lhs}_tmp"
        elem_type = vinfo.ftype if vinfo is not None else "real(kind=dp)"
        self.emit("block")
        self.indent += 3
        self.emit(f"{elem_type}, allocatable :: {tmp_name}(:)")
        self.emit(f"allocate({tmp_name}({n}))")
        self.emit(f"if (allocated({lhs})) {tmp_name}(1:min(size({lhs}), {n})) = {lhs}(1:min(size({lhs}), {n}))")
        self.emit(f"call move_alloc({tmp_name}, {lhs})")
        self.indent -= 3
        self.emit("end block")

    def _emit_fopen(self, lhs: str, fc: c_ast.FuncCall) -> bool:
        """Emit `open(newunit=...)` for a C fopen call. Returns True if emitted."""
        args = fc.args.exprs if fc.args is not None else []
        if len(args) < 2:
            return False
        fexpr = self.expr(args[0])
        mode = self.expr(args[1]).strip().strip('"').strip("'").lower()
        if "w" in mode:
            self.emit(f'open(newunit={lhs}, file={fexpr}, status="replace", action="write")')
        elif "r" in mode:
            self.emit(f'open(newunit={lhs}, file={fexpr}, status="old", action="read")')
        else:
            self.emit(f'open(newunit={lhs}, file={fexpr})')
        return True

    def emit_assignment(self, st: c_ast.Assignment, *, array_result_name: Optional[str] = None) -> None:
        if st.op == "=" and isinstance(st.rvalue, c_ast.UnaryOp) and st.rvalue.op in ("p++", "p--", "++", "--"):
            self._emit_incdec_value(self.expr(st.lvalue), st.rvalue)
            return
        # `x = tmp` where tmp aliases x collapses to a no-op.
        if st.op == "=" and isinstance(st.lvalue, c_ast.ID) and isinstance(st.rvalue, c_ast.ID):
            if self.expr(st.lvalue).lower() == self.expr(st.rvalue).lower():
                return
        if st.op != "=":
            lhs = self.expr(st.lvalue)
            rhs = self.simp(self.expr(st.rvalue))
            if st.op == "%=":
                self.emit(f"{lhs} = mod({lhs}, {rhs})")
                return
            op_map = {"+=": "+", "-=": "-", "*=": "*", "/=": "/"}
            bop = op_map.get(st.op)
            if bop is None:
                raise NotImplementedError(f"Unsupported assignment op {st.op}")
            self.emit(f"{lhs} = {self._mask_unsigned(lhs, f'{lhs} {bop} {rhs}')}")
            return

        # Chained assignment: `a = b = c = expr;` -> emit inner chain first,
        # then copy the inner target into the outer target.
        if isinstance(st.rvalue, c_ast.Assignment):
            self.emit_stmt(st.rvalue)
            self.emit(f"{self.expr(st.lvalue)} = {self.expr(st.rvalue.lvalue)}")
            return

        # Comma expression as a value: `x = (y = 3, y + 4);` -> evaluate the
        # side-effecting prefix statements, then assign the final expression.
        if isinstance(st.rvalue, c_ast.ExprList) and st.rvalue.exprs:
            for pre in st.rvalue.exprs[:-1]:
                self.emit_stmt(pre)
            self.emit(f"{self.expr(st.lvalue)} = {self.simp(self.expr(st.rvalue.exprs[-1]))}")
            return

        # Special: a[k++] = expr;
        if isinstance(st.lvalue, c_ast.ArrayRef) and isinstance(st.lvalue.subscript, c_ast.UnaryOp) and st.lvalue.subscript.op == "p++":
            arr = self.expr(st.lvalue.name)
            k = self.expr(st.lvalue.subscript.expr)
            self.emit(f"{arr}({k}+1) = {self.simp(self.expr(st.rvalue))}")
            self.emit(f"{k} = {k} + 1")
            return

        # Special malloc -> allocate. The malloc/realloc call may appear either
        # cast to a pointer type (`(T *)malloc(...)`) or bare (C implicitly
        # converts the `void *` result), so accept both forms.
        malloc_fc: Optional[c_ast.FuncCall] = None
        if isinstance(st.rvalue, c_ast.Cast) and isinstance(st.rvalue.expr, c_ast.FuncCall):
            malloc_fc = st.rvalue.expr
        elif isinstance(st.rvalue, c_ast.FuncCall):
            malloc_fc = st.rvalue
        if malloc_fc is not None and isinstance(malloc_fc.name, c_ast.ID) and malloc_fc.name.name in ("malloc", "realloc", "calloc"):
            fc = malloc_fc
            if isinstance(fc.name, c_ast.ID) and fc.name.name == "calloc" and fc.args is not None and fc.args.exprs:
                # calloc(count, size) -> allocate + zero-initialise.
                n = self._malloc_count_expr(fc.args.exprs[0])
                lhs = self.expr(st.lvalue)
                self.emit(f"allocate({lhs}({n}))")
                self.emit(f"{lhs} = 0")
                return
            if isinstance(fc.name, c_ast.ID) and fc.name.name == "realloc" and fc.args is not None and len(fc.args.exprs) >= 2:
                self._emit_realloc_grow(self.expr(st.lvalue), fc)
                return
            if isinstance(fc.name, c_ast.ID) and fc.name.name == "malloc" and fc.args is not None and fc.args.exprs:
                arg = fc.args.exprs[0]
                n = self._malloc_count_expr(arg)
                lhs = self.expr(st.lvalue)
                self.emit(f"allocate({lhs}({n}))")
                return
        # fopen -> open(newunit=...)
        if isinstance(st.rvalue, c_ast.FuncCall) and isinstance(st.rvalue.name, c_ast.ID) and st.rvalue.name.name == "fopen":
            if self._emit_fopen(self.expr(st.lvalue), st.rvalue):
                return

        # Special array-result function calls:
        # nf = factors(n, f)  ->  f = factors(n); nf = size(f)
        if isinstance(st.rvalue, c_ast.FuncCall) and isinstance(st.rvalue.name, c_ast.ID):
            fname = st.rvalue.name.name
            if fname in self.array_result_funcs and st.rvalue.args is not None:
                args = [self.expr(a) for a in st.rvalue.args.exprs]
                out_idx = self.array_result_funcs[fname]
                if 0 <= out_idx < len(args):
                    out_var = args[out_idx]
                    call_args = [a for i, a in enumerate(args) if i != out_idx]
                    lhs = self.expr(st.lvalue)
                    self.emit(f"{out_var} = {fname}({', '.join(call_args)})")
                    self.auto_alloc_assigned.add(out_var.lower())
                    self.emit(f"{lhs} = size({out_var})")
                    return

        # rand() scaling idiom -> Fortran random_number(lhs)
        if (
            isinstance(st.rvalue, c_ast.BinaryOp)
            and st.rvalue.op == "/"
            and isinstance(st.rvalue.left, c_ast.Cast)
            and isinstance(st.rvalue.left.expr, c_ast.FuncCall)
            and isinstance(st.rvalue.left.expr.name, c_ast.ID)
            and st.rvalue.left.expr.name.name == "rand"
        ):
            self.emit(f"call random_number({self.expr(st.lvalue)})")
            return

        lhs_txt = self.expr(st.lvalue)
        self.emit(f"{lhs_txt} = {self._mask_unsigned(lhs_txt, self.simp(self.expr(st.rvalue)))}")

    def _unwrap_single_stmt(self, node: Optional[c_ast.Node]) -> Optional[c_ast.Node]:
        if node is None:
            return None
        if isinstance(node, c_ast.Compound):
            items = [b for b in (node.block_items or []) if b is not None]
            if len(items) != 1:
                return None
            return items[0]
        return node

    def _is_simple_value_expr(self, n: c_ast.Node) -> bool:
        if isinstance(n, (c_ast.ID, c_ast.Constant)):
            return True
        if isinstance(n, c_ast.UnaryOp) and n.op in ("+", "-"):
            return isinstance(n.expr, (c_ast.ID, c_ast.Constant))
        return False

    def _extract_simple_update(self, st: c_ast.Node) -> Optional[Tuple[str, str, str]]:
        if not isinstance(st, c_ast.Assignment):
            return None
        lhs = self.expr(st.lvalue)
        if st.op in ("+=", "-=", "*=", "/="):
            if not self._is_simple_value_expr(st.rvalue):
                return None
            op = st.op[0]
            return lhs, op, self.simp(self.expr(st.rvalue))
        if st.op != "=":
            return None
        if not isinstance(st.rvalue, c_ast.BinaryOp):
            return None
        bop = st.rvalue.op
        if bop not in ("+", "-", "*", "/"):
            return None
        left = self.expr(st.rvalue.left)
        right = self.expr(st.rvalue.right)
        if bop in ("+", "*"):
            if left == lhs and self._is_simple_value_expr(st.rvalue.right):
                return lhs, bop, self.simp(right)
            if right == lhs and self._is_simple_value_expr(st.rvalue.left):
                return lhs, bop, self.simp(left)
            return None
        if left == lhs and self._is_simple_value_expr(st.rvalue.right):
            return lhs, bop, self.simp(right)
        return None

    def _emit_if_as_merge_update(self, st: c_ast.If) -> bool:
        if st.iffalse is None:
            return False
        t_stmt = self._unwrap_single_stmt(st.iftrue)
        f_stmt = self._unwrap_single_stmt(st.iffalse)
        if t_stmt is None or f_stmt is None:
            return False
        t_upd = self._extract_simple_update(t_stmt)
        f_upd = self._extract_simple_update(f_stmt)
        if t_upd is None or f_upd is None:
            return False
        lhs_t, op_t, val_t = t_upd
        lhs_f, op_f, val_f = f_upd
        if lhs_t != lhs_f or op_t != op_f:
            return False
        cond = self.cond_expr(st.cond)
        self.emit(f"{lhs_t} = {lhs_t} {op_t} merge({val_t}, {val_f}, {cond})")
        return True

    def _is_pointer_nullish_cond(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.UnaryOp) and node.op == "!":
            return isinstance(node.expr, c_ast.ID) and node.expr.name.lower() in self.pointer_like_names
        if isinstance(node, c_ast.BinaryOp) and node.op in ("||", "&&"):
            return self._is_pointer_nullish_cond(node.left) and self._is_pointer_nullish_cond(node.right)
        if isinstance(node, c_ast.BinaryOp) and node.op in ("==", "!="):
            lid = node.left if isinstance(node.left, c_ast.ID) else None
            rid = node.right if isinstance(node.right, c_ast.ID) else None
            lzero = isinstance(node.left, c_ast.Constant) and node.left.value in {"0", "0L"}
            rzero = isinstance(node.right, c_ast.Constant) and node.right.value in {"0", "0L"}
            if lid and rzero and lid.name.lower() in self.pointer_like_names:
                return True
            if rid and lzero and rid.name.lower() in self.pointer_like_names:
                return True
        return False

    def emit_if(self, st: c_ast.If, ret_name: Optional[str], array_result_name: Optional[str] = None) -> None:
        # sscanf result check: `if (sscanf(src, fmt, &a, ...) != N)` becomes an
        # internal read with an iostat success/failure test.
        cond = st.cond
        if (
            isinstance(cond, c_ast.BinaryOp)
            and cond.op in ("!=", "==")
            and isinstance(cond.left, c_ast.FuncCall)
            and isinstance(cond.left.name, c_ast.ID)
            and cond.left.name.name == "sscanf"
            and isinstance(cond.right, c_ast.Constant)
            and cond.left.args is not None
            and len(cond.left.args.exprs) >= 3
        ):
            fc = cond.left
            src = self.expr(fc.args.exprs[0])
            targets = ", ".join(self.expr(a) for a in fc.args.exprs[2:])
            self.emit("block")
            self.indent += 3
            self.emit("integer :: ios")
            self.emit(f"read({src}, *, iostat=ios) {targets}")
            cmp = "/=" if cond.op == "!=" else "=="
            self.emit(f"if (ios {cmp} 0) then")
            self.indent += 3
            self.emit_stmt(st.iftrue, ret_name=ret_name, array_result_name=array_result_name)
            self.indent -= 3
            if st.iffalse is not None:
                self.emit("else")
                self.indent += 3
                self.emit_stmt(st.iffalse, ret_name=ret_name, array_result_name=array_result_name)
                self.indent -= 3
            self.emit("end if")
            self.indent -= 3
            self.emit("end block")
            return
        # Short-circuit && / || whose right operand calls a function: C must
        # not evaluate the call when the left operand decides the result, so
        # build the condition stepwise with a guarded logical temporary.
        if (
            isinstance(st.cond, c_ast.BinaryOp)
            and st.cond.op in ("&&", "||")
            and _subtree_has_funccall(st.cond.right)
        ):
            self.emit("block")
            self.indent += 3
            self.emit("logical :: cond_sc")
            self.emit(f"cond_sc = {self.cond_expr(st.cond.left)}")
            if st.cond.op == "&&":
                self.emit(f"if (cond_sc) cond_sc = {self.cond_expr(st.cond.right)}")
            else:
                self.emit(f"if (.not. cond_sc) cond_sc = {self.cond_expr(st.cond.right)}")
            self.emit("if (cond_sc) then")
            self.indent += 3
            self.emit_stmt(st.iftrue, ret_name=ret_name, array_result_name=array_result_name)
            self.indent -= 3
            if st.iffalse is not None:
                self.emit("else")
                self.indent += 3
                self.emit_stmt(st.iffalse, ret_name=ret_name, array_result_name=array_result_name)
                self.indent -= 3
            self.emit("end if")
            self.indent -= 3
            self.emit("end block")
            return
        # suppress C pointer/null checks that are not needed after signature
        # lowering — except for true POINTER entities, whose NULL tests become
        # meaningful associated() checks.
        if isinstance(st.cond, c_ast.BinaryOp) and st.cond.op in ("==", "!="):
            l_is_null = isinstance(st.cond.left, c_ast.ID) and st.cond.left.name == "NULL"
            r_is_null = isinstance(st.cond.right, c_ast.ID) and st.cond.right.name == "NULL"
            if l_is_null or r_is_null:
                other = st.cond.right if l_is_null else st.cond.left
                if not self._is_ptr_entity(other) and not self._is_alloc_entity(other):
                    return
        if self._is_pointer_nullish_cond(st.cond):
            return
        if self._emit_if_as_merge_update(st):
            return
        self.emit(f"if ({self.cond_expr(st.cond)}) then")
        self.indent += 3
        self.emit_stmt(st.iftrue, ret_name=ret_name, array_result_name=array_result_name)
        self.indent -= 3
        if st.iffalse is not None:
            self.emit("else")
            self.indent += 3
            self.emit_stmt(st.iffalse, ret_name=ret_name, array_result_name=array_result_name)
            self.indent -= 3
        self.emit("end if")

    def _contains_break(self, node: c_ast.Node) -> bool:
        if isinstance(node, c_ast.Break):
            return True
        return any(
            isinstance(child, c_ast.Node) and self._contains_break(child)
            for _name, child in node.children()
        )

    def emit_switch(
        self,
        st: c_ast.Switch,
        ret_name: Optional[str],
        array_result_name: Optional[str] = None,
    ) -> None:
        """Lower a conservative, non-fallthrough C switch to SELECT CASE."""
        if not isinstance(st.stmt, c_ast.Compound):
            raise NotImplementedError("Switch body must be a compound statement")
        arms = list(st.stmt.block_items or [])
        if not arms or not all(isinstance(arm, (c_ast.Case, c_ast.Default)) for arm in arms):
            raise NotImplementedError("Only direct case/default switch arms are supported")

        normalized: List[Tuple[c_ast.Node, List[c_ast.Node]]] = []
        for index, arm in enumerate(arms):
            statements = list(arm.stmts or [])
            terminal_break = bool(statements and isinstance(statements[-1], c_ast.Break))
            if terminal_break:
                statements.pop()
            if index < len(arms) - 1 and not terminal_break:
                raise NotImplementedError("C switch fallthrough is not supported")
            if any(self._contains_break(stmt) for stmt in statements):
                raise NotImplementedError("Conditional switch breaks are not supported")
            normalized.append((arm, statements))

        self.emit(f"select case ({self.expr(st.cond)})")
        self.indent += 3
        for arm, statements in normalized:
            if isinstance(arm, c_ast.Case):
                self.emit(f"case ({self.expr(arm.expr)})")
            else:
                self.emit("case default")
            self.indent += 3
            for statement in statements:
                self.emit_stmt(
                    statement,
                    ret_name=ret_name,
                    array_result_name=array_result_name,
                )
            self.indent -= 3
        self.indent -= 3
        self.emit("end select")

    def emit_stmt(
        self,
        st: c_ast.Node,
        ret_name: Optional[str] = None,
        array_result_name: Optional[str] = None,
    ) -> None:
        if st is None:
            return
        coord = getattr(st, "coord", None)
        if coord is not None and getattr(coord, "line", None):
            src_line = int(coord.line) - self.line_offset
            if src_line >= 1:
                # Carry over only the nearest local comment cluster for this
                # statement to avoid pulling unrelated comments from earlier code.
                self.emit_leading_comments_before(src_line, window=2)
        if isinstance(st, c_ast.Compound):
            for b in st.block_items or []:
                self.emit_stmt(b, ret_name=ret_name, array_result_name=array_result_name)
            return
        if isinstance(st, c_ast.Decl):
            # declarations already hoisted
            if st.init is not None:
                info = self.var_infos.get((st.name or "").lower())
                if info is not None and info.struct_ptr:
                    init = st.init.expr if isinstance(st.init, c_ast.Cast) else st.init
                    if isinstance(init, c_ast.ID) and init.name == "NULL":
                        self.emit(f"{st.name} => null()")
                        return
                    if isinstance(init, c_ast.FuncCall) and isinstance(init.name, c_ast.ID) and init.name.name == "malloc":
                        self.emit(f"allocate({st.name})")
                        return
                    self.emit(f"{st.name} => {self.expr(init)}")
                    return
                if isinstance(st.init, c_ast.InitList) and info is not None and info.funcptr_array:
                    # Function-pointer array: point each element's procedure
                    # pointer at the named module function.
                    for k, e in enumerate(st.init.exprs or [], start=1):
                        if isinstance(e, c_ast.ID):
                            self.emit(f"{st.name}({k})%fp => {e.name}")
                    return
                if isinstance(st.init, c_ast.InitList) and info is not None and info.shape and info.char_string:
                    # Array of C strings: a typed constructor pads shorter
                    # literals to the common declared length.
                    vals = ", ".join(self.expr(e) for e in (st.init.exprs or []))
                    self.emit(f"{st.name} = [{info.ftype} :: {vals}]")
                    return
                if isinstance(st.init, c_ast.InitList) and info is not None and info.shape:
                    struct_elem = re.match(r"^type\(([^)]+)\)$", info.ftype, re.IGNORECASE)
                    if struct_elem is not None and struct_elem.group(1).lower() in self.struct_defs:
                        # Array of structs: build a per-element constructor list.
                        elems = [
                            self._struct_constructor(struct_elem.group(1), e)
                            if isinstance(e, c_ast.InitList) else self.expr(e)
                            for e in (st.init.exprs or [])
                        ]
                        self.emit(f"{st.name} = [{', '.join(elems)}]")
                        return
                    flat_values = self._flatten_init_list(st.init)
                    real_target = info.ftype.lower().startswith("real")
                    values = ", ".join(self._init_elem_expr(value, real_target) for value in flat_values)
                    shape = self._rename_ids_in_text(", ".join(info.shape))
                    if len(flat_values) == 1 and (len(info.shape) > 1 or info.shape[0] != "1"):
                        # C `= {0}` / `= {{0}}` zero-fills the whole array:
                        # broadcast the single value.
                        self.emit(f"{st.name} = {values}")
                    elif len(info.shape) == 1:
                        self.emit(f"{st.name} = [{values}]")
                    else:
                        self.emit(f"{st.name} = reshape([{values}], [{shape}])")
                    return
                if isinstance(st.init, c_ast.InitList) and info is not None:
                    struct_match = re.match(r"^type\(([^)]+)\)$", info.ftype, re.IGNORECASE)
                    if struct_match and struct_match.group(1).lower() in self.struct_defs:
                        ctor = self._struct_constructor(struct_match.group(1), st.init)
                        self.emit(f"{st.name} = {ctor}")
                        return
                if isinstance(st.init, c_ast.UnaryOp) and st.init.op in ("p++", "p--", "++", "--"):
                    self._emit_incdec_value(st.name, st.init)
                    return
                if isinstance(st.init, c_ast.Constant) and st.init.value == "NULL":
                    return
                if isinstance(st.init, c_ast.ID) and st.init.name == "NULL":
                    return
                # Declaration-initialized malloc -> allocate (cast or bare).
                init_fc: Optional[c_ast.FuncCall] = None
                if isinstance(st.init, c_ast.Cast) and isinstance(st.init.expr, c_ast.FuncCall):
                    init_fc = st.init.expr
                elif isinstance(st.init, c_ast.FuncCall):
                    init_fc = st.init
                if (
                    st.name
                    and st.name.lower() in self.alias_map
                    and init_fc is not None
                    and isinstance(init_fc.name, c_ast.ID)
                    and init_fc.name.name == "realloc"
                    and init_fc.args is not None
                    and len(init_fc.args.exprs) >= 2
                ):
                    # `T *tmp = realloc(x, n)`: grow x in place; tmp aliases x.
                    self._emit_realloc_grow(self.alias_map[st.name.lower()], init_fc)
                    return
                if init_fc is not None and isinstance(init_fc.name, c_ast.ID) and init_fc.name.name == "malloc" and init_fc.args is not None and init_fc.args.exprs:
                    arg = init_fc.args.exprs[0]
                    flex = self._flex_member_for(st.name)
                    if flex is not None:
                        # malloc(sizeof(*v) + n*sizeof(elem)): the extra bytes
                        # size the flexible member; allocate that component.
                        count_node = arg.right if isinstance(arg, c_ast.BinaryOp) and arg.op == "+" else arg
                        n = self._malloc_count_expr(count_node)
                        self.emit(f"allocate({st.name}%{flex}({n}))")
                        return
                    n = self._malloc_count_expr(arg)
                    self.emit(f"allocate({st.name}({n}))")
                    return
                if init_fc is not None and isinstance(init_fc.name, c_ast.ID) and init_fc.name.name == "calloc" and init_fc.args is not None and init_fc.args.exprs:
                    n = self._malloc_count_expr(init_fc.args.exprs[0])
                    self.emit(f"allocate({st.name}({n}))")
                    self.emit(f"{st.name} = 0")
                    return
                if isinstance(st.init, c_ast.FuncCall) and isinstance(st.init.name, c_ast.ID) and st.init.name.name == "fopen":
                    if self._emit_fopen(st.name, st.init):
                        return
                if isinstance(st.init, c_ast.FuncCall) and isinstance(st.init.name, c_ast.ID):
                    fname = st.init.name.name
                    if fname in self.array_result_funcs and st.init.args is not None:
                        args = [self.expr(a) for a in st.init.args.exprs]
                        out_idx = self.array_result_funcs[fname]
                        if 0 <= out_idx < len(args):
                            out_var = args[out_idx]
                            call_args = [a for i, a in enumerate(args) if i != out_idx]
                            self.emit(f"{out_var} = {fname}({', '.join(call_args)})")
                            self.auto_alloc_assigned.add(out_var.lower())
                            self.emit(f"{st.name} = size({out_var})")
                            return
                self.emit(f"{st.name} = {self.expr(st.init)}")
            return
        if isinstance(st, c_ast.Assignment):
            # POINTER-entity targets use pointer assignment / allocation.
            if st.op == "=" and self._is_ptr_entity(st.lvalue):
                lhs = self.expr(st.lvalue)
                rv = st.rvalue.expr if isinstance(st.rvalue, c_ast.Cast) else st.rvalue
                if isinstance(rv, c_ast.ID) and rv.name == "NULL":
                    self.emit(f"{lhs} => null()")
                    return
                if isinstance(rv, c_ast.FuncCall) and isinstance(rv.name, c_ast.ID) and rv.name.name == "malloc":
                    self.emit(f"allocate({lhs})")
                    return
                if self._is_ptr_entity(rv) or (isinstance(rv, c_ast.UnaryOp) and rv.op == "&"):
                    self.emit(f"{lhs} => {self.expr(rv)}")
                    return
            # suppress *out = NULL
            if isinstance(st.lvalue, c_ast.UnaryOp) and st.lvalue.op == "*" and isinstance(st.rvalue, c_ast.ID) and st.rvalue.name == "NULL":
                return
            if isinstance(st.rvalue, c_ast.Constant) and st.rvalue.value == "NULL":
                return
            if isinstance(st.rvalue, c_ast.ID) and st.rvalue.name == "NULL":
                return
            if self.array_result_name is not None:
                if isinstance(st.lvalue, c_ast.ID) and st.lvalue.name == self.array_result_name:
                    if isinstance(st.rvalue, c_ast.ID) and self.expr(st.rvalue).strip() == self.array_result_name:
                        return
            if isinstance(st.lvalue, c_ast.UnaryOp) and st.lvalue.op == "*" and isinstance(st.lvalue.expr, c_ast.ID):
                if self.array_result_name is not None and st.lvalue.expr.name == self.array_result_name:
                    if isinstance(st.rvalue, c_ast.ID) and self.expr(st.rvalue).strip() == self.array_result_name:
                        return
            self.emit_assignment(st, array_result_name=array_result_name)
            return
        if isinstance(st, c_ast.Return):
            if st.expr is None:
                self.emit("return")
            elif array_result_name is not None:
                expr_txt = self.simp(self.expr(st.expr)).strip().lower()
                if expr_txt in {"0", "0.0", "0.0d0", "0.0d+0"}:
                    self.emit(f"allocate({array_result_name}(0))")
                self.emit("return")
            elif ret_name is None:
                self.emit("stop")
            else:
                self.emit(f"{ret_name} = {self.expr(st.expr)}")
                self.emit("return")
            return
        if isinstance(st, c_ast.If):
            self.emit_if(st, ret_name=ret_name, array_result_name=array_result_name)
            return
        if isinstance(st, c_ast.Switch):
            self.emit_switch(st, ret_name=ret_name, array_result_name=array_result_name)
            return
        if isinstance(st, c_ast.For):
            self.emit_for(st, ret_name=ret_name, array_result_name=array_result_name)
            return
        if isinstance(st, c_ast.While):
            # while (fscanf(fp, "...", &v) == 1) { ... } -> read loop with iostat
            cond = st.cond
            if (
                isinstance(cond, c_ast.BinaryOp)
                and cond.op == "=="
                and isinstance(cond.right, c_ast.Constant)
                and isinstance(cond.left, c_ast.FuncCall)
                and isinstance(cond.left.name, c_ast.ID)
                and cond.left.name.name == "fscanf"
                and cond.left.args is not None
                and len(cond.left.args.exprs) >= 3
                and str(cond.right.value).strip().isdigit()
                and int(cond.right.value) == len(cond.left.args.exprs) - 2
            ):
                fp_expr = self.expr(cond.left.args.exprs[0])
                read_targets = ", ".join(self.expr(a) for a in cond.left.args.exprs[2:])
                self.emit("block")
                self.indent += 3
                self.emit("integer :: ios")
                self.emit("do")
                self.indent += 3
                self.emit(f"read({fp_expr}, *, iostat=ios) {read_targets}")
                self.emit("if (ios /= 0) exit")
                self.emit_stmt(st.stmt, ret_name=ret_name, array_result_name=array_result_name)
                self.indent -= 3
                self.emit("end do")
                self.indent -= 3
                self.emit("end block")
                return
            self.emit(f"do while ({self.cond_expr(st.cond)})")
            self.indent += 3
            self.emit_stmt(st.stmt, ret_name=ret_name, array_result_name=array_result_name)
            self.indent -= 3
            self.emit("end do")
            return
        if isinstance(st, c_ast.DoWhile):
            # C do-while runs the body once before testing the condition.
            self.emit("do")
            self.indent += 3
            self.emit_stmt(st.stmt, ret_name=ret_name, array_result_name=array_result_name)
            self.emit(f"if (.not. ({self.cond_expr(st.cond)})) exit")
            self.indent -= 3
            self.emit("end do")
            return
        if isinstance(st, c_ast.FuncCall):
            if isinstance(st.name, c_ast.ID) and st.name.name == "printf":
                self.emit_printf(st)
                return
            if isinstance(st.name, c_ast.ID) and st.name.name == "puts":
                args = st.args.exprs if st.args is not None else []
                if len(args) == 1:
                    a0 = args[0]
                    if (
                        isinstance(a0, c_ast.Constant)
                        and a0.type == "string"
                        and a0.value.strip() in {'""', 'L""', 'u8""', 'u""', 'U""'}
                    ):
                        self.emit("print *")
                    else:
                        self.emit(f"write(*,'(a)') {self.expr(a0)}")
                else:
                    self.emit("write(*,*)")
                return
            if isinstance(st.name, c_ast.ID) and st.name.name == "qsort":
                # qsort(arr, n, size, cmp) -> generated ascending sort helper.
                args = st.args.exprs if st.args is not None else []
                if len(args) >= 2:
                    arr = self.expr(args[0])
                    n = self.expr(args[1])
                    ainfo = self.var_infos.get(arr.lower())
                    kind = "real" if (ainfo is not None and ainfo.ftype.lower().startswith("real")) else "int"
                    self.emit(f"call c2f_sort_{kind}({arr}(1:{n}))")
                    return
            if isinstance(st.name, c_ast.ID) and st.name.name in ("memset", "memcpy", "memmove"):
                # memset(dst, v, n) fills with v; memcpy(dst, src, n) copies.
                # Either way the second argument is the whole-array RHS here.
                args = st.args.exprs if st.args is not None else []
                if len(args) == 3:
                    self.emit(f"{self.expr(args[0])} = {self.expr(args[1])}")
                    return
            if isinstance(st.name, c_ast.ID) and st.name.name in ("strcat", "strcpy"):
                args = st.args.exprs if st.args is not None else []
                if len(args) == 2:
                    dst = self.expr(args[0])
                    src = self.expr(args[1])
                    if st.name.name == "strcpy":
                        self.emit(f"{dst} = {src}")
                    else:
                        # Deferred-length strings hold their exact value; fixed
                        # buffers carry blank padding that must be trimmed first.
                        dinfo = self.var_infos.get(dst.lower())
                        dst_expr = dst if (dinfo is not None and dinfo.alloc) else f"trim({dst})"
                        self.emit(f"{dst} = {dst_expr} // {src}")
                    return
            if isinstance(st.name, c_ast.ID) and st.name.name == "sprintf":
                args = st.args.exprs if st.args is not None else []
                if len(args) >= 2 and isinstance(args[1], c_ast.Constant) and args[1].type == "string":
                    buf = self.expr(args[0])
                    lines = self._translate_printf(args[1].value, list(args[2:]), unit=buf, internal=True)
                    if lines is not None:
                        for line in lines:
                            self.emit(line)
                        return
            if isinstance(st.name, c_ast.ID) and st.name.name == "sscanf":
                args = st.args.exprs if st.args is not None else []
                if len(args) >= 3:
                    src = self.expr(args[0])
                    targets = ", ".join(self.expr(a) for a in args[2:])
                    self.emit(f"read({src}, *) {targets}")
                    return
            if isinstance(st.name, c_ast.ID) and st.name.name in ("exit", "_Exit", "abort"):
                args = st.args.exprs if st.args is not None else []
                code = self.expr(args[0]) if args else "0"
                self.emit(f"stop {code}" if code.strip() not in ("", "0") else "stop")
                return
            if isinstance(st.name, c_ast.ID) and st.name.name in ("putchar", "putc"):
                args = st.args.exprs if st.args is not None else []
                if args:
                    self.emit(f"write(*, '(a)', advance=\"no\") {self.expr(args[0])}")
                return
            if isinstance(st.name, c_ast.ID) and st.name.name == "srand":
                # deterministic seed handled by generated Fortran runtime defaults
                return
            if isinstance(st.name, c_ast.ID) and st.name.name == "fclose":
                args = st.args.exprs if st.args is not None else []
                if len(args) == 1:
                    self.emit(f"close({self.expr(args[0])})")
                return
            if isinstance(st.name, c_ast.ID) and st.name.name == "fprintf":
                args = st.args.exprs if st.args is not None else []
                if len(args) >= 2:
                    unit = self.expr(args[0])
                    if isinstance(args[1], c_ast.Constant) and args[1].type == "string":
                        lines = self._translate_printf(args[1].value, list(args[2:]), unit=unit)
                        if lines is not None:
                            for line in lines:
                                self.emit(line)
                            return
                    if len(args) >= 3:
                        self.emit(f"write({unit},*) {', '.join(self.expr(a) for a in args[2:])}")
                    else:
                        self.emit(f"write({unit},*)")
                    return
            if isinstance(st.name, c_ast.ID) and st.name.name == "free":
                args = st.args.exprs if st.args is not None else []
                if len(args) == 1:
                    v = self.expr(args[0])
                    if v.lower() in self.auto_alloc_assigned:
                        return
                    if v.lower() in self.struct_ptr_names:
                        self.emit(f"deallocate({v})")
                        return
                    flex = self._flex_member_for(v)
                    if flex is not None:
                        # The struct itself is a scalar; only its flexible
                        # member holds an allocation.
                        self.emit(f"if (allocated({v}%{flex})) deallocate({v}%{flex})")
                        return
                    self.emit(f"if (allocated({v})) deallocate({v})")
                return
            call_name = st.name.name if isinstance(st.name, c_ast.ID) else self.expr(st.name)
            call_args = self._lower_call_args(call_name, st.args.exprs if st.args else [])
            self.emit(f"call {self.expr(st.name)}({', '.join(call_args)})")
            return
        if isinstance(st, c_ast.UnaryOp):
            if st.op in {"p++", "++"}:
                v = self.expr(st.expr)
                self.emit(f"{v} = {v} + 1")
                return
            if st.op in {"p--", "--"}:
                v = self.expr(st.expr)
                self.emit(f"{v} = {v} - 1")
                return
        if isinstance(st, c_ast.BinaryOp) and st.op == ",":
            # Comma expression used as statement: evaluate both sides for side effects.
            self.emit_stmt(st.left, ret_name=ret_name, array_result_name=array_result_name)
            self.emit_stmt(st.right, ret_name=ret_name, array_result_name=array_result_name)
            return
        if isinstance(st, c_ast.EmptyStatement):
            return
        if isinstance(st, c_ast.Break):
            self.emit("exit")
            return
        if isinstance(st, c_ast.Continue):
            self.emit("cycle")
            return
        if isinstance(st, c_ast.Label):
            num = self.label_map.get(st.name)
            if num is None:
                num = 1000 + len(self.label_map)
                self.label_map[st.name] = num
            # A numeric-labelled CONTINUE lets any statement carry a target.
            self.emit(f"{num} continue")
            self.emit_stmt(st.stmt, ret_name=ret_name, array_result_name=array_result_name)
            return
        if isinstance(st, c_ast.Goto):
            num = self.label_map.get(st.name)
            if num is None:
                num = 1000 + len(self.label_map)
                self.label_map[st.name] = num
            self.emit(f"go to {num}")
            return
        raise NotImplementedError(f"Unsupported stmt: {type(st).__name__}")


def emit_rand_helper(em: Emitter) -> None:
    """Emit a Fortran `rand()` returning an integer in [0, RAND_MAX].

    C's ``rand()`` has no direct Fortran intrinsic; approximate it with the
    intrinsic pseudorandom generator scaled to the C ``RAND_MAX`` range.
    """
    em.emit("function rand() result(rand_result)")
    em.emit("! integer pseudorandom value in [0, RAND_MAX], approximating C rand()")
    em.emit("integer :: rand_result")
    em.emit("real(kind=dp) :: rand_r")
    em.emit("call random_number(rand_r)")
    em.emit("rand_result = int(rand_r * 2147483648.0_dp)")
    em.emit("end function rand")


def _register_funcptr_arrays(em: Emitter, body: c_ast.Node, locals_map: Dict[str, VarInfo]) -> None:
    """Record function-pointer array locals and their interface function."""
    names = {n.lower() for n, info in locals_map.items() if info.funcptr_array}
    if not names:
        return

    def visit(node: c_ast.Node) -> None:
        if (
            isinstance(node, c_ast.Decl)
            and node.name
            and node.name.lower() in names
            and isinstance(node.init, c_ast.InitList)
        ):
            for e in node.init.exprs or []:
                if isinstance(e, c_ast.ID):
                    em.funcptr_arrays[node.name.lower()] = e.name
                    break
        for _k, child in node.children():
            if isinstance(child, c_ast.Node):
                visit(child)

    visit(body)


def emit_funcptr_wrapper_type(em: Emitter) -> None:
    """Emit the wrapper type holding one procedure pointer per element."""
    iface = next(iter(em.funcptr_arrays.values()))
    em.emit("type :: c2f_procptr")
    em.emit(f"   procedure({iface}), pointer, nopass :: fp")
    em.emit("end type c2f_procptr")


def _demote_nonarray_pointer_locals(em: Emitter, body: c_ast.Node, locals_map: Dict[str, VarInfo]) -> None:
    """Treat pointer locals never used as arrays as plain scalars.

    C code like `int *p = NULL; set_value(&p, &x); printf("%d", *p);` uses the
    pointer only for aliasing a scalar; value semantics (a plain scalar passed
    with intent(out)) reproduces the observable behavior.
    """
    names = {n.lower() for n, info in locals_map.items() if info.alloc and not info.char_string}
    if not names:
        return
    keep: Set[str] = set()

    def visit(node: c_ast.Node) -> None:
        if isinstance(node, c_ast.ArrayRef) and isinstance(node.name, c_ast.ID):
            keep.add(node.name.name.lower())
        # Pointer arithmetic (p + i) marks p as an array view.
        if isinstance(node, c_ast.BinaryOp) and node.op in ("+", "-"):
            for side in (node.left, node.right):
                if isinstance(side, c_ast.ID):
                    keep.add(side.name.lower())
        # Aliasing an array (`p = x` / `int *p = x`) keeps array semantics.
        if isinstance(node, c_ast.Assignment) and isinstance(node.lvalue, c_ast.ID) and isinstance(node.rvalue, c_ast.ID) and node.rvalue.name != "NULL":
            keep.add(node.lvalue.name.lower())
        if isinstance(node, c_ast.Decl) and node.name and isinstance(node.init, c_ast.ID) and node.init.name != "NULL":
            keep.add(node.name.lower())
        if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID) and node.args is not None:
            fname = node.name.name
            if fname in ("malloc", "calloc", "realloc", "free"):
                for a in node.args.exprs:
                    if isinstance(a, c_ast.ID):
                        keep.add(a.name.lower())
            arr_idxs = em.array_param_funcs.get(fname, set())
            for idx, a in enumerate(node.args.exprs):
                if idx in arr_idxs:
                    if isinstance(a, c_ast.ID):
                        keep.add(a.name.lower())
                    elif isinstance(a, c_ast.UnaryOp) and isinstance(a.expr, c_ast.ID):
                        keep.add(a.expr.name.lower())
        # A malloc-family call in a declaration initializer also keeps it.
        if isinstance(node, c_ast.Decl) and node.name and node.init is not None:
            init = node.init.expr if isinstance(node.init, c_ast.Cast) else node.init
            if isinstance(init, c_ast.FuncCall) and isinstance(init.name, c_ast.ID) and init.name.name in ("malloc", "calloc", "realloc"):
                keep.add(node.name.lower())
        for _k, child in node.children():
            if isinstance(child, c_ast.Node):
                visit(child)

    visit(body)
    for n, info in locals_map.items():
        if n.lower() in names and n.lower() not in keep:
            info.alloc = False


def _register_realloc_aliases(em: Emitter, body: c_ast.Node, locals_map: Dict[str, VarInfo]) -> None:
    """Fold `T *tmp = realloc(x, ...)` into a growth of x with tmp aliasing x.

    The aliased local is dropped from the declaration set; references to it
    resolve to the realloc target, and `x = tmp` collapses to a no-op.
    """
    def visit(node: c_ast.Node) -> None:
        if isinstance(node, c_ast.Decl) and node.name and node.init is not None:
            init = node.init
            if isinstance(init, c_ast.Cast):
                init = init.expr
            if (
                isinstance(init, c_ast.FuncCall)
                and isinstance(init.name, c_ast.ID)
                and init.name.name == "realloc"
                and init.args is not None
                and init.args.exprs
                and isinstance(init.args.exprs[0], c_ast.ID)
            ):
                target = init.args.exprs[0].name
                if node.name in locals_map and target.lower() != node.name.lower():
                    em.alias_map[node.name.lower()] = target
                    locals_map.pop(node.name, None)
        for _k, child in node.children():
            if isinstance(child, c_ast.Node):
                visit(child)

    visit(body)


def emit_argv_helper(em: Emitter) -> None:
    """Emit argv_value(pos): the pos-th command-line argument as a string."""
    em.emit("function argv_value(pos) result(argv_value_result)")
    em.emit("! command-line argument at position pos (0 is the command name)")
    em.emit("integer, intent(in) :: pos")
    em.emit("character(len=:), allocatable :: argv_value_result")
    em.emit("integer :: arg_len")
    em.emit("call get_command_argument(pos, length=arg_len)")
    em.emit("allocate(character(len=arg_len) :: argv_value_result)")
    em.emit("call get_command_argument(pos, value=argv_value_result)")
    em.emit("end function argv_value")


def emit_used_defines(em: Emitter, body: c_ast.Node, taken: Optional[Set[str]] = None) -> None:
    """Emit `parameter` declarations for `#define` constants used in `body`.

    C is case-sensitive, so `#define K` and a local `k` can coexist; Fortran is
    not, so the parameter is renamed on a case-insensitive collision.
    """
    if not em.define_constants:
        return
    taken_low = {t.lower() for t in (taken or set())}
    for name, (ftype, value) in em.define_constants.items():
        if not ast_uses_any_id(body, {name}):
            continue
        out_name = name
        if name.lower() in taken_low:
            out_name = f"{name}_const"
            while out_name.lower() in taken_low:
                out_name += "_"
            em.id_rename[name] = out_name
        em.emit(f"{ftype}, parameter :: {out_name} = {value}")


def emit_function(
    fn: c_ast.FuncDef,
    em: Emitter,
    *,
    main_use_names: Optional[List[str]] = None,
    c_arg_comments_by_func: Optional[Dict[str, Dict[str, str]]] = None,
    c_header_comments_by_func: Optional[Dict[str, str]] = None,
) -> None:
    decl = fn.decl
    fdecl = decl.type
    if not isinstance(fdecl, c_ast.FuncDecl):
        raise NotImplementedError("Expected FuncDecl")
    em.label_map = {}
    name = decl.name
    c_arg_comments = (c_arg_comments_by_func or {}).get(name.lower(), {})
    c_header_comment = (c_header_comments_by_func or {}).get(name.lower())
    low_name = name.lower()
    if "min_max" in low_name and (not c_header_comment or "sum" in c_header_comment.lower()):
        c_header_comment = "return min and max of vector"
    if "sum_vec" in low_name and (not c_header_comment or "min and max" in c_header_comment.lower()):
        c_header_comment = "return sum of vector"
    fn_src_line: Optional[int] = None
    if decl.coord is not None and getattr(decl.coord, "line", None):
        src_line = int(decl.coord.line) - em.line_offset
        if src_line >= 1:
            fn_src_line = src_line

    params: List[c_ast.Decl] = []
    if fdecl.args is not None:
        params = [p for p in fdecl.args.params if isinstance(p, c_ast.Decl)]
    need_ieee_consts = ast_uses_any_id(fn.body, {"NAN", "INFINITY", "HUGE_VAL"})
    need_ieee_finite = bool(collect_called_names(fn.body, {"isfinite"}))
    ieee_imports: List[str] = []
    if need_ieee_consts:
        ieee_imports.extend(["ieee_value", "ieee_quiet_nan", "ieee_positive_inf"])
    if need_ieee_finite:
        ieee_imports.append("ieee_is_finite")
    is_recursive = name in collect_called_names(fn.body, {name})

    need_int64 = ast_uses_any_id(fn.body, {"UINT_MAX", "LONG_MAX"}) or _body_has_unsigned_locals(fn.body)

    if name == "main":
        em.emit("program main")
        if main_use_names:
            em.emit(f"use xc2f_mod, only: {', '.join(main_use_names)}")
        em.emit("use, intrinsic :: iso_fortran_env, only: real64")
        if need_int64:
            em.emit("use, intrinsic :: iso_fortran_env, only: int64")
        if ieee_imports:
            em.emit(f"use, intrinsic :: ieee_arithmetic, only: {', '.join(ieee_imports)}")
        em.emit("implicit none")
        for enum_name, enum_value in em.enum_constants.items():
            em.emit(f"integer, parameter :: {enum_name} = {enum_value}")

        locals_map: Dict[str, VarInfo] = {}
        gather_decls(fn.body, locals_map)
        _register_realloc_aliases(em, fn.body, locals_map)
        _demote_nonarray_pointer_locals(em, fn.body, locals_map)
        _register_funcptr_arrays(em, fn.body, locals_map)
        # C main(argc, argv): argc maps onto command_argument_count()+1 (the
        # command name is argument 0 in both models) and argv[i] onto the
        # argv_value() helper.
        argc_assign: Optional[str] = None
        for p in params:
            if not p.name or not ast_uses_any_id(fn.body, {p.name}):
                continue
            p_ft, _ = c_to_ftype(p.type)
            if p_ft == "integer" and not type_is_ptr_or_array(p.type):
                locals_map[p.name] = VarInfo(ftype="integer")
                argc_assign = f"{p.name} = command_argument_count() + 1"
            elif _classify_char_decl(p.type) == "array":
                em.argv_name = p.name.lower()
        emit_used_defines(em, fn.body, taken=set(locals_map.keys()))
        em.var_infos = {k.lower(): v for k, v in locals_map.items()}
        for n, info in locals_map.items():
            if info.struct_ptr:
                em.struct_ptr_names.add(n.lower())
                continue
            if info.char_string:
                if not info.shape:
                    em.char_string_names.add(n.lower())
                continue
            if info.alloc:
                em.pointer_like_names.add(n.lower())
        em.indent = 0
        if em.funcptr_arrays:
            emit_funcptr_wrapper_type(em)
        em.emit_decl_grouped(locals_map, params=set(), ret_name=None)
        if argc_assign is not None:
            em.emit(argc_assign)
        em.emit_stmt(fn.body, ret_name=None)
        em.emit("end program main")
        em.pointer_like_names.clear()
        em.char_string_names.clear()
        em.id_rename = {}
        em.argv_name = None
        em.alias_map = {}
        em.funcptr_arrays = {}
        em.struct_ptr_names.clear()
        em.var_infos = {}
        return

    # non-main -> Fortran function
    ret_ftype, _ = c_to_ftype(fdecl.type)
    out_idx = em.array_result_funcs.get(name, None)
    out_param_name: Optional[str] = None
    out_c_param_name: Optional[str] = None
    pnames: List[str] = []
    for idx, p in enumerate(params):
        if out_idx is not None and idx == out_idx:
            out_c_param_name = p.name
            out_param_name = p.name
            continue
        pnames.append(p.name)

    result_name_for_body: Optional[str] = None
    result_decl_ftype: Optional[str] = None
    recursive_prefix = "recursive " if is_recursive else ""
    if out_idx is not None:
        em.emit(f"{recursive_prefix}function {name}({', '.join(pnames)}) result({out_param_name})")
        unit_kind = "function"
        result_name_for_body = out_param_name
    elif ret_ftype.lower() == "void":
        em.emit(f"{recursive_prefix}subroutine {name}({', '.join(pnames)})")
        unit_kind = "subroutine"
    else:
        result_name_for_body = f"{name}_result"
        em.emit(f"{recursive_prefix}function {name}({', '.join(pnames)}) result({result_name_for_body})")
        unit_kind = "function"
        result_decl_ftype = ret_ftype
        if ret_ftype.lower().startswith("character"):
            # A char*-returning C function yields an exact-length string.
            result_decl_ftype = "character(len=:), allocatable"
    em.emit(f"! {proc_docline(name, unit_kind)}")
    if c_header_comment:
        em.lines[-1] = f"! {c_header_comment}"
    if fn_src_line is not None:
        comments = em.pop_leading_comments_before(fn_src_line)
        filtered: List[str] = []
        seen: Set[str] = set()
        for c in comments:
            c0 = c.strip()
            if not c0:
                continue
            key = c0.lower()
            if key in seen:
                continue
            seen.add(key)
            filtered.append(c0)
        header_doc: Optional[str] = None
        arg_comment_re = re.compile(r"^[a-z_]\w*\s*:\s*", re.IGNORECASE)
        for c0 in filtered:
            if not arg_comment_re.match(c0):
                header_doc = c0
                break
        param_comment_map: Dict[str, str] = {}
        for c0 in filtered:
            mpc = re.match(r"^([a-z_]\w*)\s*:\s*(.+)$", c0, re.IGNORECASE)
            if not mpc:
                continue
            pname = mpc.group(1).lower()
            ptxt = mpc.group(2).strip()
            if ptxt and pname not in param_comment_map:
                param_comment_map[pname] = ptxt
        if header_doc and not c_header_comment:
            # Replace generic auto-doc with source comment when available.
            if em.lines and em.lines[-1].lstrip().startswith("!"):
                em.lines[-1] = f"! {header_doc}"
        # Keep generated procedure docline only; imported C comments tend to be
        # noisy/redundant after transpilation round-trips.
        comments = []
        if out_idx is not None:
            rewritten: List[str] = []
            for c in comments:
                low = c.lower()
                if "return value is" in low and "number of factors" in low:
                    rewritten.append("- return value is the factors array (size(...) gives count; empty on error)")
                else:
                    rewritten.append(c)
            comments = rewritten
        for c in comments:
            em.emit(f"! {c}")
        if em.comment_cursor <= fn_src_line:
            em.comment_cursor = fn_src_line + 1
    else:
        param_comment_map = {}
    em.emit("use, intrinsic :: iso_fortran_env, only: real64")
    if need_int64:
        em.emit("use, intrinsic :: iso_fortran_env, only: int64")
    if ieee_imports:
        em.emit(f"use, intrinsic :: ieee_arithmetic, only: {', '.join(ieee_imports)}")
    for enum_name, enum_value in em.enum_constants.items():
        em.emit(f"integer, parameter :: {enum_name} = {enum_value}")
    _fn_locals: Dict[str, VarInfo] = {}
    gather_decls(fn.body, _fn_locals)
    emit_used_defines(
        em, fn.body, taken=set(_fn_locals.keys()) | {p.name for p in params if p.name}
    )

    param_set = set(pnames)
    # params
    for idx, p in enumerate(params):
        if out_idx is not None and idx == out_idx:
            continue
        if isinstance(p.type, c_ast.PtrDecl) and isinstance(p.type.type, c_ast.FuncDecl):
            iface = em.func_ptr_ifaces.get((name, idx))
            if iface is not None:
                # C function-pointer parameter: a dummy procedure with the
                # interface of a function actually passed at some call site.
                em.emit(f"procedure({iface}) :: {p.name}")
                continue
        if isinstance(p.type, c_ast.PtrDecl):
            pf_ptr, _ = c_to_ftype(p.type)
            mrec_p = re.match(r"^type\(([^)]+)\)$", pf_ptr, re.IGNORECASE)
            if mrec_p is not None and mrec_p.group(1).lower() in _STRUCT_RECURSIVE:
                # Pointer to a recursive struct: a POINTER dummy. intent(in)
                # lets a TARGET actual associate the pointer on entry (F2008).
                em.emit(f"{pf_ptr}, pointer, intent(in) :: {p.name}")
                em.struct_ptr_names.add(p.name.lower())
                continue
        p_ft, p_alloc = c_to_ftype(p.type)
        p_ptr_or_arr = type_is_ptr_or_array(p.type)
        p_const = type_has_const(p.type)
        if p_const:
            intent = "intent(in)"
        else:
            has_read, has_write = _scan_dummy_usage(fn.body, p.name)
            if idx in em.writable_param_funcs.get(name, set()):
                has_write = True
            first_read, first_write = _dummy_first_read_write_line(fn.body, p.name)
            if has_write and (not has_read or (first_write is not None and (first_read is None or first_write < first_read))):
                intent = "intent(out)"
            elif has_write:
                intent = "intent(inout)"
            else:
                intent = "intent(in)"
        is_array_dummy = idx in em.array_param_funcs.get(name, set())
        # A non-const pointer to a struct is conventionally mutated by the
        # callee (its members are updated in place, often via address-of-member
        # passed to a helper). Usage scanning cannot see those indirect writes,
        # so default such a scalar struct pointer to intent(inout).
        if (
            not p_const
            and p_ptr_or_arr
            and not is_array_dummy
            and p_ft.lower().startswith("type(")
            and intent == "intent(in)"
        ):
            intent = "intent(inout)"
        inline_doc = c_arg_comments.get(p.name.lower()) or param_comment_map.get(p.name.lower()) or arg_docline(
            p.name, p_ft, intent=intent, is_array=is_array_dummy
        )
        if _classify_char_decl(p.type) == "scalar":
            # A C string parameter is one assumed-length character scalar.
            em.emit(add_inline_comment(f"character(len=*), {intent} :: {p.name}", inline_doc))
            em.char_string_names.add(p.name.lower())
        elif p_ptr_or_arr and is_array_dummy:
            rank = max(1, dummy_array_rank(p.type))
            dims = ", ".join([":"] * rank)
            em.emit(add_inline_comment(f"{p_ft}, {intent} :: {p.name}({dims})", inline_doc))
            if rank == 1:
                em.pointer_like_names.add(p.name.lower())
        else:
            em.emit(add_inline_comment(f"{p_ft}, {intent} :: {p.name}", inline_doc))
    if out_idx is not None and out_param_name is not None:
        em.emit(add_inline_comment(f"integer, allocatable :: {out_param_name}(:)", arg_docline(out_param_name, "integer")))
        em.array_result_name = out_param_name
    elif unit_kind == "function" and result_name_for_body is not None and result_decl_ftype is not None:
        em.emit(f"{result_decl_ftype} :: {result_name_for_body}")

    # locals
    locals_map: Dict[str, VarInfo] = {}
    gather_decls(fn.body, locals_map)
    _register_realloc_aliases(em, fn.body, locals_map)
    _demote_nonarray_pointer_locals(em, fn.body, locals_map)
    _register_funcptr_arrays(em, fn.body, locals_map)
    em.var_infos = {k.lower(): v for k, v in locals_map.items()}
    for n, info in locals_map.items():
        if info.struct_ptr:
            em.struct_ptr_names.add(n.lower())
            continue
        if info.char_string:
            if not info.shape:
                em.char_string_names.add(n.lower())
            continue
        if info.alloc:
            em.pointer_like_names.add(n.lower())
    if out_idx is not None and out_param_name is not None:
        # If function body includes `*out = tmp` and tmp is allocatable local,
        # alias tmp -> out and avoid declaring tmp.
        body_items = fn.body.block_items or []
        for st in body_items:
            if isinstance(st, c_ast.Assignment) and st.op == "=":
                l = st.lvalue
                r = st.rvalue
                if isinstance(l, c_ast.UnaryOp) and l.op == "*" and isinstance(l.expr, c_ast.ID):
                    if out_c_param_name is not None and l.expr.name == out_c_param_name and isinstance(r, c_ast.ID):
                        tmp = r.name
                        info = locals_map.get(tmp)
                        if info is not None and info.alloc:
                            em.array_result_tmp_alias = tmp
                            del locals_map[tmp]
                            break
    if em.funcptr_arrays:
        emit_funcptr_wrapper_type(em)
    em.emit_decl_grouped(locals_map, params=param_set, ret_name=result_name_for_body if unit_kind == "function" else None)

    # body
    em.emit_stmt(
        fn.body,
        ret_name=result_name_for_body if unit_kind == "function" else None,
        array_result_name=out_param_name if out_idx is not None else None,
    )
    if unit_kind == "subroutine":
        em.emit(f"end subroutine {name}")
    else:
        em.emit(f"end function {name}")
    em.array_result_name = None
    em.array_result_tmp_alias = None
    em.pointer_like_names.clear()
    em.char_string_names.clear()
    em.id_rename = {}
    em.alias_map = {}
    em.funcptr_arrays = {}
    em.struct_ptr_names.clear()
    em.var_infos = {}


# C identifiers that would collide with Fortran statement keywords in emitted
# positions (e.g. a C function literally named `function`).
_FORTRAN_UNIT_KEYWORDS: Set[str] = {
    "function", "subroutine", "result", "program", "contains", "end",
    "block", "interface", "procedure", "module",
}


def rename_ast_identifiers(node: c_ast.Node, mapping: Dict[str, str]) -> None:
    """Rename identifiers (definitions and references) throughout the AST."""
    for attr in ("name", "declname"):
        v = getattr(node, attr, None)
        if isinstance(v, str) and v in mapping:
            setattr(node, attr, mapping[v])
    for _k, child in node.children():
        if isinstance(child, c_ast.Node):
            rename_ast_identifiers(child, mapping)


def collect_keyword_collision_renames(ast_root: c_ast.FileAST) -> Dict[str, str]:
    """Map C identifiers named like Fortran unit keywords to safe names."""
    found: Set[str] = set()

    def visit(node: c_ast.Node) -> None:
        for attr in ("name", "declname"):
            v = getattr(node, attr, None)
            if isinstance(v, str) and v.lower() in _FORTRAN_UNIT_KEYWORDS:
                found.add(v)
        for _k, child in node.children():
            if isinstance(child, c_ast.Node):
                visit(child)

    visit(ast_root)
    return {n: f"{n}_f" for n in found}


def collect_called_names(node: c_ast.Node, names: Set[str]) -> Set[str]:
    """Collect function-call names that match `names` from an AST subtree."""
    found: Set[str] = set()
    if isinstance(node, c_ast.FuncCall) and isinstance(node.name, c_ast.ID):
        n = node.name.name
        if n in names:
            found.add(n)
    for _k, child in node.children():
        if isinstance(child, c_ast.Node):
            found.update(collect_called_names(child, names))
    return found


def collect_struct_type_uses(node: c_ast.Node, struct_names: Set[str]) -> Set[str]:
    """Collect struct type names used via compound literals in a subtree."""
    found: Set[str] = set()
    if isinstance(node, c_ast.CompoundLiteral):
        tnode = node.type.type if isinstance(node.type, c_ast.Typename) else node.type
        ftype, _ = c_to_ftype(tnode)
        m = re.match(r"^type\(([^)]+)\)$", ftype, re.IGNORECASE)
        if m is not None and m.group(1).lower() in struct_names:
            found.add(m.group(1).lower())
    for _k, child in node.children():
        if isinstance(child, c_ast.Node):
            found |= collect_struct_type_uses(child, struct_names)
    return found


def ast_uses_any_id(node: c_ast.Node, names: Set[str]) -> bool:
    """True if subtree references any identifier in `names`."""
    if isinstance(node, c_ast.ID) and node.name in names:
        return True
    for _k, child in node.children():
        if isinstance(child, c_ast.Node) and ast_uses_any_id(child, names):
            return True
    return False


def _is_dummy_target_expr(expr: c_ast.Node, pname: str) -> bool:
    """True when AST expr refers to dummy argument pname or *pname."""
    if isinstance(expr, c_ast.ID):
        return expr.name == pname
    if isinstance(expr, c_ast.ArrayRef):
        return _is_dummy_target_expr(expr.name, pname)
    if isinstance(expr, c_ast.StructRef):
        return _is_dummy_target_expr(expr.name, pname)
    if isinstance(expr, c_ast.UnaryOp) and expr.op == "*" and isinstance(expr.expr, c_ast.ID):
        return expr.expr.name == pname
    return False


def _scan_dummy_usage(node: c_ast.Node, pname: str, *, write_ctx: bool = False) -> Tuple[bool, bool]:
    """Return (has_read, has_write) usage for dummy pname in subtree."""
    has_read = False
    has_write = False

    if isinstance(node, c_ast.Assignment):
        if _is_dummy_target_expr(node.lvalue, pname):
            has_write = True
        r_read, r_write = _scan_dummy_usage(node.rvalue, pname, write_ctx=False)
        has_read = has_read or r_read
        has_write = has_write or r_write
        # lvalue subscripts/struct refs may contain reads
        l_read, l_write = _scan_dummy_usage(node.lvalue, pname, write_ctx=True)
        has_read = has_read or l_read
        has_write = has_write or l_write
        return has_read, has_write

    if isinstance(node, c_ast.UnaryOp) and node.op in ("p++", "p--", "++", "--"):
        if _is_dummy_target_expr(node.expr, pname):
            return True, True

    if _is_dummy_target_expr(node, pname):
        if write_ctx:
            return False, False
        return True, False

    for _k, child in node.children():
        if isinstance(child, c_ast.Node):
            c_read, c_write = _scan_dummy_usage(child, pname, write_ctx=write_ctx)
            has_read = has_read or c_read
            has_write = has_write or c_write
    return has_read, has_write


def _dummy_first_read_write_line(
    node: c_ast.Node,
    pname: str,
    *,
    write_ctx: bool = False,
) -> Tuple[Optional[int], Optional[int]]:
    """Return earliest (read_line, write_line) for dummy pname in subtree."""
    first_read: Optional[int] = None
    first_write: Optional[int] = None

    def _line_of(n: c_ast.Node) -> Optional[int]:
        c = getattr(n, "coord", None)
        if c is None:
            return None
        return getattr(c, "line", None)

    if isinstance(node, c_ast.Assignment):
        r_read, r_write = _dummy_first_read_write_line(node.rvalue, pname, write_ctx=False)
        l_read, l_write = _dummy_first_read_write_line(node.lvalue, pname, write_ctx=True)
        for v in (r_read, l_read):
            if v is not None and (first_read is None or v < first_read):
                first_read = v
        for v in (r_write, l_write):
            if v is not None and (first_write is None or v < first_write):
                first_write = v
        if _is_dummy_target_expr(node.lvalue, pname):
            ln = _line_of(node)
            if ln is not None and (first_write is None or ln < first_write):
                first_write = ln
        return first_read, first_write

    if isinstance(node, c_ast.UnaryOp) and node.op in ("p++", "p--", "++", "--"):
        if _is_dummy_target_expr(node.expr, pname):
            ln = _line_of(node)
            return ln, ln

    if _is_dummy_target_expr(node, pname):
        if write_ctx:
            return None, None
        ln = _line_of(node)
        return ln, None

    for _k, child in node.children():
        if isinstance(child, c_ast.Node):
            c_read, c_write = _dummy_first_read_write_line(child, pname, write_ctx=write_ctx)
            if c_read is not None and (first_read is None or c_read < first_read):
                first_read = c_read
            if c_write is not None and (first_write is None or c_write < first_write):
                first_write = c_write
    return first_read, first_write


def transpile_c_to_fortran(
    text: str,
    *,
    refactor: bool = False,
    raw: bool = False,
    pure: bool = False,
    elemental: bool = False,
) -> str:
    no_pp = strip_preprocessor_only(text)
    comments = extract_preserved_comments(no_pp)
    c_arg_comments_by_func = extract_c_function_arg_comments(no_pp)
    c_header_comments_by_func = extract_c_function_header_comments(no_pp)
    src = normalize_c_complex_types(
        normalize_fortran_d_exponents(strip_preprocessor_and_comments(text))
    )
    src = expand_function_macros(src, collect_func_macros(text))
    parser = c_parser.CParser()
    ast = parser.parse(PRELUDE + "\n" + src)
    keyword_renames = collect_keyword_collision_renames(ast)
    if keyword_renames:
        rename_ast_identifiers(ast, keyword_renames)
    real_prec = _detect_c_real_precision(src)
    dp_init = "kind(1.0)" if real_prec == "single" else "kind(1.0d0)"
    struct_defs = collect_struct_typedefs(ast)
    enum_constants = collect_enum_constants(ast)
    define_constants = collect_define_constants(text)
    generic_macros = collect_generic_macros(text)
    global _STRUCT_TYPEDEFS
    _STRUCT_TYPEDEFS = set(struct_defs.keys())

    line_offset = PRELUDE.count("\n") + 1
    array_result_funcs: Dict[str, int] = {}
    for ext in ast.ext:
        if not isinstance(ext, c_ast.FuncDef):
            continue
        decl = ext.decl
        fdecl = decl.type
        if not isinstance(fdecl, c_ast.FuncDecl):
            continue
        ret_ftype, _ = c_to_ftype(fdecl.type)
        if ret_ftype.lower() != "integer":
            continue
        if fdecl.args is None:
            continue
        params = [p for p in fdecl.args.params if isinstance(p, c_ast.Decl)]
        for idx, p in enumerate(params):
            _pft, p_alloc = c_to_ftype(p.type)
            if p_alloc and p.name and p.name.lower() == "out":
                array_result_funcs[decl.name] = idx
                break

    em = Emitter(
        comment_map=comments,
        line_offset=line_offset,
        array_result_funcs=array_result_funcs,
        enum_constants=enum_constants,
        struct_defs=struct_defs,
        define_constants=define_constants,
        generic_macros=generic_macros,
    )
    for ext in ast.ext:
        if not isinstance(ext, c_ast.FuncDef) or not isinstance(ext.decl.type, c_ast.FuncDecl):
            continue
        fdecl = ext.decl.type
        fparams = [p for p in fdecl.args.params if isinstance(p, c_ast.Decl)] if fdecl.args else []
        idxs = {
            idx for idx, p in enumerate(fparams)
            if p.name and type_is_ptr_or_array(p.type) and has_array_ref_of(ext.body, p.name)
        }
        if idxs:
            em.array_param_funcs[ext.decl.name] = idxs
        writable_idxs = {
            idx
            for idx, p in enumerate(fparams)
            if p.name and _scan_dummy_usage(ext.body, p.name)[1]
        }
        if writable_idxs:
            em.writable_param_funcs[ext.decl.name] = writable_idxs

    # Propagate array rank through forwarding wrappers. A parameter may never
    # be indexed in its own function but still be passed to another function's
    # array dummy (for example weight -> categorical_random(weight)).
    changed = True
    while changed:
        changed = False
        for ext in ast.ext:
            if not isinstance(ext, c_ast.FuncDef) or not isinstance(ext.decl.type, c_ast.FuncDecl):
                continue
            fdecl = ext.decl.type
            fparams = [p for p in fdecl.args.params if isinstance(p, c_ast.Decl)] if fdecl.args else []
            idxs = em.array_param_funcs.setdefault(ext.decl.name, set())
            for idx, p in enumerate(fparams):
                if idx in idxs or not p.name or not type_is_ptr_or_array(p.type):
                    continue
                if is_forwarded_to_array_parameter(ext.body, p.name, em.array_param_funcs):
                    idxs.add(idx)
                    changed = True

    # Propagate writes through wrapper calls just as array rank is propagated.
    # A caller dummy forwarded to an OUT/INOUT callee cannot remain INTENT(IN).
    changed = True
    while changed:
        changed = False
        for ext in ast.ext:
            if not isinstance(ext, c_ast.FuncDef) or not isinstance(ext.decl.type, c_ast.FuncDecl):
                continue
            fdecl = ext.decl.type
            fparams = [p for p in fdecl.args.params if isinstance(p, c_ast.Decl)] if fdecl.args else []
            writable_idxs = em.writable_param_funcs.setdefault(ext.decl.name, set())
            for idx, p in enumerate(fparams):
                if idx in writable_idxs or not p.name:
                    continue
                if is_forwarded_to_array_parameter(
                    ext.body,
                    p.name,
                    em.writable_param_funcs,
                    include_struct_components=True,
                ):
                    writable_idxs.add(idx)
                    changed = True

    funcs = [e for e in ast.ext if isinstance(e, c_ast.FuncDef) and e.decl.name != "main"]
    mains = [e for e in ast.ext if isinstance(e, c_ast.FuncDef) and e.decl.name == "main"]
    externally_visible_func_names = {
        e.decl.name for e in funcs if "static" not in (e.decl.storage or [])
    }
    # qsort comparators take const void* arguments, which have no value-level
    # translation; qsort calls become a generated sort helper and the
    # comparator functions are dropped.
    funcs = [e for e in funcs if not _has_void_ptr_param(e)]
    if mains:
        # A standalone C program may contain unused static helpers. Emitting
        # them as private module procedures trips -Werror=unused-function, so
        # retain only the transitive call graph rooted at main (including
        # functions passed by name as function-pointer arguments).
        funcs_by_name = {e.decl.name: e for e in funcs}
        candidate_names = set(funcs_by_name)
        reachable: Set[str] = set()
        pending_funcs: List[str] = []
        for main_fn in mains:
            roots = collect_called_names(main_fn.body, candidate_names)
            roots.update(
                fname for fname in candidate_names if ast_uses_any_id(main_fn.body, {fname})
            )
            pending_funcs.extend(roots)
        while pending_funcs:
            fname = pending_funcs.pop()
            if fname in reachable or fname not in funcs_by_name:
                continue
            reachable.add(fname)
            body = funcs_by_name[fname].body
            callees = collect_called_names(body, candidate_names)
            callees.update(
                other for other in candidate_names if ast_uses_any_id(body, {other})
            )
            pending_funcs.extend(callees - reachable)
        funcs = [
            e
            for e in funcs
            if e.decl.name in reachable or e.decl.name in externally_visible_func_names
        ]
    qsort_kinds = _collect_qsort_elem_kinds(ast)
    retained_units = funcs + mains
    uses_rand = any(collect_called_names(unit.body, {"rand"}) for unit in retained_units)
    main_uses_rand = any(collect_called_names(m, {"rand"}) for m in mains)
    uses_argv = False
    for m in mains:
        margs = m.decl.type.args
        for p in (margs.params if margs is not None else []):
            if (
                isinstance(p, c_ast.Decl)
                and p.name
                and _classify_char_decl(p.type) == "array"
                and ast_uses_any_id(m.body, {p.name})
            ):
                uses_argv = True
    module_proc_names: Set[str] = {e.decl.name for e in funcs}

    # Resolve C function-pointer parameters to dummy-procedure interfaces:
    # for each such parameter, find a module function passed at any call site.
    func_ptr_param_idx: Dict[str, List[int]] = {}
    for e in funcs + mains:
        fd = e.decl.type
        fps = [p for p in (fd.args.params if fd.args else []) if isinstance(p, c_ast.Decl)]
        fp_idxs = [
            i for i, p in enumerate(fps)
            if isinstance(p.type, c_ast.PtrDecl) and isinstance(p.type.type, c_ast.FuncDecl)
        ]
        if fp_idxs:
            func_ptr_param_idx[e.decl.name] = fp_idxs
    if func_ptr_param_idx:
        def _scan_fp_calls(node: c_ast.Node) -> None:
            if (
                isinstance(node, c_ast.FuncCall)
                and isinstance(node.name, c_ast.ID)
                and node.name.name in func_ptr_param_idx
                and node.args is not None
            ):
                for i in func_ptr_param_idx[node.name.name]:
                    if i < len(node.args.exprs):
                        a = node.args.exprs[i]
                        if isinstance(a, c_ast.ID) and a.name in module_proc_names:
                            em.func_ptr_ifaces.setdefault((node.name.name, i), a.name)
            for _k, child in node.children():
                if isinstance(child, c_ast.Node):
                    _scan_fp_calls(child)
        _scan_fp_calls(ast)

    main_called_module_names: Set[str] = set()
    main_needed_types: Set[str] = set()
    for m in mains:
        main_called_module_names.update(collect_called_names(m, module_proc_names))
        # Module functions passed by name (e.g. as function-pointer actuals)
        # must also be imported.
        for pname in module_proc_names:
            if ast_uses_any_id(m.body, {pname}):
                main_called_module_names.add(pname)
        # Struct types referenced by main via compound literals / constructors
        # (not just declared variables) must also be imported.
        main_needed_types |= collect_struct_type_uses(m.body, set(struct_defs.keys()))
        lmap: Dict[str, VarInfo] = {}
        gather_decls(m.body, lmap)
        for _n, info in lmap.items():
            mty = re.match(r"^\s*type\s*\(\s*([a-z][a-z0-9_]*)\s*\)\s*$", info.ftype, re.IGNORECASE)
            if mty:
                tname = mty.group(1).lower()
                if tname in struct_defs:
                    main_needed_types.add(tname)

    # Pull in struct types referenced transitively (nested components) so their
    # constructors resolve in main.
    pending = list(main_needed_types)
    while pending:
        cur = pending.pop()
        sdef = struct_defs.get(cur)
        if sdef is None:
            continue
        for _fn, ft, _sh in sdef.fields:
            mt = re.match(r"^type\(([^)]+)\)$", ft, re.IGNORECASE)
            if mt is not None:
                dep = mt.group(1).lower()
                if dep in struct_defs and dep not in main_needed_types:
                    main_needed_types.add(dep)
                    pending.append(dep)

    # File-scope variables become shared module variables.
    global_vars: List[Tuple[str, str, Optional[str], Optional[Tuple[str, ...]]]] = []
    gvar_names: Set[str] = set()
    for ext in ast.ext:
        if not isinstance(ext, c_ast.Decl) or not ext.name:
            continue
        if isinstance(ext.type, (c_ast.FuncDecl, c_ast.Struct, c_ast.Union, c_ast.Enum)):
            continue
        gftype, _galloc = c_to_ftype(ext.type)
        if gftype == "void":
            continue
        vinfo_map: Dict[str, VarInfo] = {}
        gather_decls(ext, vinfo_map)
        gshape = vinfo_map.get(ext.name).shape if vinfo_map.get(ext.name) else None
        ginit = None
        if ext.init is not None and not isinstance(ext.init, c_ast.InitList):
            ginit = em.expr(ext.init)
        global_vars.append((ext.name, gftype, ginit, gshape))
        gvar_names.add(ext.name)
    main_used_gvars = sorted(
        n for n in gvar_names if any(ast_uses_any_id(m.body, {n}) for m in mains)
    )

    # Emit a module whenever there are module procedures, a rand()/argv
    # helper, struct type definitions, or shared global variables.
    if funcs or uses_rand or uses_argv or struct_defs or global_vars or qsort_kinds:
        em.emit("module xc2f_mod")
        em.emit("implicit none")
        em.emit("private")
        if mains:
            publics = sorted(set(main_called_module_names) | set(main_needed_types))
            publics.extend(
                sorted(externally_visible_func_names & {e.decl.name for e in funcs})
            )
            if main_uses_rand:
                publics.append("rand")
            if uses_argv:
                publics.append("argv_value")
            publics.extend(f"c2f_sort_{k}" for k in sorted(qsort_kinds))
        else:
            publics = sorted(module_proc_names)
        publics.extend(sorted(struct_defs.keys()))
        publics.extend(sorted(gvar_names))
        publics = sorted(set(publics))
        if publics:
            em.emit(f"public :: {', '.join(publics)}")
        if struct_defs:
            em.emit("")
            for sname in sorted(struct_defs.keys()):
                sdef = struct_defs[sname]
                em.emit(f"type :: {sdef.name}")
                for fname, ftype, shape in sdef.fields:
                    if shape == ":":
                        em.emit(f"   {ftype}, allocatable :: {fname}(:)")
                    elif shape == "*":
                        em.emit(f"   {ftype}, pointer :: {fname} => null()")
                    elif shape:
                        em.emit(f"   {ftype} :: {fname}({shape})")
                    else:
                        em.emit(f"   {ftype} :: {fname}")
                em.emit(f"end type {sdef.name}")
                em.emit("")
        if global_vars:
            em.emit("")
            for gname, gftype, ginit, gshape in global_vars:
                decl = f"{gftype} :: {gname}"
                if gshape:
                    decl = f"{gftype} :: {gname}({', '.join(gshape)})"
                if ginit is not None:
                    decl += f" = {ginit}"
                em.emit(decl)
            em.emit("")
        if funcs or uses_rand or uses_argv or qsort_kinds:
            em.emit("contains")
            em.emit("")
            for ext in funcs:
                emit_function(
                    ext,
                    em,
                    c_arg_comments_by_func=c_arg_comments_by_func,
                    c_header_comments_by_func=c_header_comments_by_func,
                )
                em.emit("")
            if uses_rand:
                emit_rand_helper(em)
                em.emit("")
            if uses_argv:
                emit_argv_helper(em)
                em.emit("")
            for k in sorted(qsort_kinds):
                emit_qsort_helper(em, k)
                em.emit("")
        em.emit("end module xc2f_mod")
        em.emit("")

    main_use_names = sorted(set(main_called_module_names) | set(main_needed_types) | set(main_used_gvars))
    if main_uses_rand:
        main_use_names.append("rand")
    if uses_argv:
        main_use_names.append("argv_value")
    main_use_names.extend(f"c2f_sort_{k}" for k in sorted(qsort_kinds))
    for ext in mains:
        emit_function(
            ext,
            em,
            main_use_names=main_use_names,
            c_arg_comments_by_func=c_arg_comments_by_func,
            c_header_comments_by_func=c_header_comments_by_func,
        )
        em.emit("")
    lines = [ln + "\n" for ln in em.lines]
    if raw:
        # Raw mode: return direct lowering output with minimal wrapping only.
        out_text = "".join(lines).rstrip() + "\n"
        return out_text

    lines = fscan.demote_fixed_size_single_allocatables(lines)
    lines = _coalesce_simple_declarations_preserve_intent(lines)
    lines = fscan.coalesce_adjacent_allocate_statements(lines, max_len=80)
    lines = move_decl_comments_to_after_signature(lines)
    lines = move_inits_below_early_guard(lines)
    lines = fscan.promote_scalar_constants_to_parameters(lines)
    lines = remove_redundant_final_return(lines)
    lines = remove_redundant_final_stop(lines)
    lines = fscan.remove_redundant_tail_deallocations(lines)
    lines = collapse_noadvance_integer_print_loops(lines)
    lines = apply_dead_store_cleanup(lines)
    lines = fscan.inline_temp_assign_into_immediate_use(lines, require_write_stmt=True)
    lines = inline_single_use_temp_assignments(lines)
    lines = fpost.inline_temp_into_function_result(lines)
    lines = fpost.remove_redundant_self_assignments(lines)
    lines = fpost.normalize_shifted_index_loops(lines)
    lines = fpost.remove_redundant_size_dummy_args(lines)
    lines = fpost.hoist_repeated_open_file_literals(lines)
    lines = apply_dead_store_cleanup(lines)
    lines = fscan.prune_unused_use_only_lines(lines)
    lines = fpost.hoist_module_use_only_imports(lines)
    lines = fscan.avoid_reserved_identifier_definitions(lines)
    lines = fpost.simplify_redundant_parentheses(lines)
    lines = fpost.tighten_unary_minus_literal_spacing(lines)
    lines = fpost.normalize_delimiter_inner_spacing(lines)
    lines = fpost.simplify_norm2_patterns(lines)
    lines = fpost.simplify_bfgs_rank1_update(lines)
    lines = fscan.simplify_integer_arithmetic_in_lines(lines)
    lines = fpost.collapse_single_stmt_if_blocks(lines)
    lines = fpost.simplify_do_while_true(lines)
    lines = fpost.ensure_blank_line_between_module_procedures(lines)
    lines = fscan.collapse_random_number_element_loops(lines)
    lines = fscan.coalesce_contiguous_scalar_assignments_to_constructor(lines)
    lines = _remove_arg_style_doc_comments(lines)
    if pure or elemental:
        lines = add_pure_when_possible(lines)
    if elemental:
        lines = fpost.promote_pure_scalar_subroutines_to_elemental(lines)
    out_text = "".join(lines).rstrip() + "\n"
    if array_result_funcs:
        out_text = out_text.replace(
            "! - return value is the number of factors (0 on error)\n",
            "! - return value is the factors array (size(...) gives count; empty on error)\n",
        )
    out_text, _n_alloc_assign = xalloc_assign.rewrite_text_allocation_on_assignment(out_text)
    out_text, _n_adv = xadvance.rewrite_text_collapse_nonadv_write_loops(out_text)
    out_lines = out_text.splitlines(keepends=True)
    out_lines = fscan.remove_redundant_int_casts(out_lines)
    out_lines = fscan.remove_redundant_real_casts(out_lines)
    out_lines = rewrite_realloc_assign_patterns(out_lines)
    out_lines = fscan.compact_consecutive_constructor_literals_to_implied_do(out_lines, min_items=4)
    out_lines = fscan.normalize_identifier_case_to_declarations(out_lines)
    out_lines = fscan.demote_fixed_size_single_allocatables(out_lines)
    out_lines = fscan.suffix_real_literals_with_kind(out_lines, kind_name="dp")
    out_lines = collapse_int_array_write_implied_do(out_lines)
    out_lines = fpost.ensure_function_result_syntax(out_lines)
    out_lines = fpost.remove_unused_local_declarations(out_lines)
    out_lines = fscan.ensure_space_before_inline_comments(out_lines)
    out_text = "".join(out_lines)
    out_text = _normalize_kind_intrinsic_literals(out_text)
    out_text = apply_shared_kind_module_dp(out_text, dp_init=dp_init)
    if refactor:
        out_text = fref.refactor_long_main_blocks_to_module_subroutines(out_text)
        out_text = "".join(apply_dead_store_cleanup(out_text.splitlines(keepends=True)))
        out_text = "".join(fscan.coalesce_simple_declarations(out_text.splitlines(keepends=True)))
        out_text = "".join(fpost.remove_unused_local_declarations(out_text.splitlines(keepends=True)))
    out_text = "".join(fscan.prune_unused_use_only_lines(out_text.splitlines(keepends=True)))
    out_text = "".join(fpost.simplify_redundant_parentheses(out_text.splitlines(keepends=True)))
    out_text = "".join(fpost.tighten_unary_minus_literal_spacing(out_text.splitlines(keepends=True)))
    out_text = "".join(fpost.normalize_delimiter_inner_spacing(out_text.splitlines(keepends=True)))
    out_text = "".join(fpost.simplify_bfgs_rank1_update(out_text.splitlines(keepends=True)))
    out_text = "".join(fscan.simplify_do_bounds_parens(out_text.splitlines(keepends=True)))
    out_text = "".join(fpost.rewrite_named_arguments(out_text.splitlines(keepends=True)))
    out_text = "".join(fpost.wrap_long_lines(out_text.splitlines(keepends=True), max_len=80))
    out_text = "".join(fpost.apply_xindent_defaults(out_text.splitlines(keepends=True), max_len=80))
    out_text = "".join(fpost.ensure_blank_line_between_module_procedures(out_text.splitlines(keepends=True)))
    out_text = "".join(fpost.ensure_blank_line_between_program_units(out_text.splitlines(keepends=True)))
    out_text = "".join(fscan.ensure_space_before_inline_comments(out_text.splitlines(keepends=True)))
    out_text = _normalize_kind_intrinsic_literals(out_text)
    return out_text


def apply_xarray_postprocess(text: str, *, inline: bool = False) -> str:
    """Run xarray.py as an optional final post-pass on generated Fortran."""
    xarray_path = Path(__file__).with_name("xarray.py")
    if not xarray_path.exists():
        return text
    with tempfile.TemporaryDirectory(prefix="xc2f_array_") as td:
        tdir = Path(td)
        src = tdir / "in.f90"
        out = tdir / "out.f90"
        src.write_text(text, encoding="utf-8")
        cmd = [
            sys.executable,
            str(xarray_path),
            str(src),
            "--fix",
            "--out",
            str(out),
            "--no-trace",
            "--no-annotate",
        ]
        if inline:
            cmd.append("--inline")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return text
        if out.exists():
            return out.read_text(encoding="utf-8", errors="ignore")
        return text


def apply_xno_variable_postprocess(text: str) -> str:
    """Run xno_variable.py optional post-pass on generated Fortran."""
    tool_path = Path(__file__).with_name("xno_variable.py")
    if not tool_path.exists():
        return text
    with tempfile.TemporaryDirectory(prefix="xc2f_inline_") as td:
        tdir = Path(td)
        src = tdir / "in.f90"
        out = tdir / "out.f90"
        src.write_text(text, encoding="utf-8")
        cmd = [
            sys.executable,
            str(tool_path),
            str(src),
            "--fix",
            "--out",
            str(out),
            "--no-backup",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return text
        if out.exists():
            return out.read_text(encoding="utf-8", errors="ignore")
        return text


def _build_and_run(
    source: Path,
    *,
    compiler: str,
    exe_path: Path,
    label: str,
    extra_args: Optional[List[str]] = None,
) -> Tuple[bool, str, str, bool]:
    if shutil.which(compiler) is None:
        print(f"Run ({label}): SKIP ({compiler} not found)")
        return False, "", "", False
    extra = extra_args or []
    cmd = [compiler, str(source), *extra, "-o", str(exe_path)]
    print(f"Build ({label}): {' '.join(cmd)}")
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        print(f"Build ({label}): FAIL (exit {cp.returncode})")
        if cp.stdout:
            print(cp.stdout.rstrip())
        if cp.stderr:
            print(cp.stderr.rstrip())
        return False, cp.stdout or "", cp.stderr or "", False
    print(f"Build ({label}): PASS")
    print(f"Run ({label}): {exe_path}")
    rp = subprocess.run([str(exe_path)], capture_output=True, text=True)
    if rp.returncode != 0:
        print(f"Run ({label}): FAIL (exit {rp.returncode})")
        if rp.stdout:
            print(rp.stdout.rstrip())
        if rp.stderr:
            print(rp.stderr.rstrip())
        return False, rp.stdout or "", rp.stderr or "", True
    print(f"Run ({label}): PASS")
    if rp.stdout:
        print(rp.stdout.rstrip())
    if rp.stderr:
        print(rp.stderr.rstrip())
    return True, rp.stdout or "", rp.stderr or "", True


def _build_and_run_c_many(
    sources: List[Path],
    *,
    exe_path: Path,
    label: str,
) -> Tuple[bool, str, str, bool]:
    if shutil.which("gcc") is None:
        print(f"Run ({label}): SKIP (gcc not found)")
        return False, "", "", False
    cmd = ["gcc", *[str(p) for p in sources], "-lm", "-o", str(exe_path)]
    print(f"Build ({label}): {' '.join(cmd)}")
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        print(f"Build ({label}): FAIL (exit {cp.returncode})")
        if cp.stdout:
            print(cp.stdout.rstrip())
        if cp.stderr:
            print(cp.stderr.rstrip())
        return False, cp.stdout or "", cp.stderr or "", False
    print(f"Build ({label}): PASS")
    print(f"Run ({label}): {exe_path}")
    rp = subprocess.run([str(exe_path)], capture_output=True, text=True)
    if rp.returncode != 0:
        print(f"Run ({label}): FAIL (exit {rp.returncode})")
        if rp.stdout:
            print(rp.stdout.rstrip())
        if rp.stderr:
            print(rp.stderr.rstrip())
        return False, rp.stdout or "", rp.stderr or "", True
    print(f"Run ({label}): PASS")
    if rp.stdout:
        print(rp.stdout.rstrip())
    if rp.stderr:
        print(rp.stderr.rstrip())
    return True, rp.stdout or "", rp.stderr or "", True


def _build_only_cmd(cmd: List[str], *, label: str) -> bool:
    print(f"Build ({label}): {' '.join(cmd)}")
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        print(f"Build ({label}): FAIL (exit {cp.returncode})")
        if cp.stdout:
            print(cp.stdout.rstrip())
        if cp.stderr:
            print(cp.stderr.rstrip())
        return False
    print(f"Build ({label}): PASS")
    return True


def _requested_actions_succeeded(
    args: argparse.Namespace,
    *,
    original_run_ok: bool,
    original_build_ok: bool,
    fortran_run_ok: bool,
    fortran_build_ok: bool,
) -> bool:
    """Return whether every build/run action requested on the CLI succeeded."""
    if args.run_both:
        return original_run_ok and fortran_run_ok
    if args.run:
        return fortran_run_ok
    if args.compile_both or args.compile_both_c:
        return original_build_ok and fortran_build_ok
    if args.compile or args.compile_c:
        return fortran_build_ok
    return True


def _build_c_many_only(
    sources: List[Path],
    *,
    exe_path: Path,
    label: str,
    compile_only: bool,
) -> bool:
    if shutil.which("gcc") is None:
        print(f"Build ({label}): SKIP (gcc not found)")
        return False
    if compile_only:
        ok = True
        for src in sources:
            obj = src.with_suffix(".orig.o")
            cmd = ["gcc", "-c", str(src), "-o", str(obj)]
            ok = _build_only_cmd(cmd, label=label) and ok
        return ok
    cmd = ["gcc", *[str(p) for p in sources], "-lm", "-o", str(exe_path)]
    return _build_only_cmd(cmd, label=label)


def _time_executable(exe_path: Path, *, label: str, reps: int = 3) -> Optional[float]:
    """Return best wall time over reps in seconds, or None on failure."""
    best: Optional[float] = None
    for _ in range(max(1, reps)):
        t0 = time.perf_counter()
        rp = subprocess.run([str(exe_path)], capture_output=True, text=True)
        dt = time.perf_counter() - t0
        if rp.returncode != 0:
            print(f"Time ({label}): FAIL (exit {rp.returncode})")
            if rp.stdout:
                print(rp.stdout.rstrip())
            if rp.stderr:
                print(rp.stderr.rstrip())
            return None
        if best is None or dt < best:
            best = dt
    if best is not None:
        print(f"Time ({label}): best {best:.6f} s over {max(1, reps)} run(s)")
    return best


def apply_shared_kind_module_dp(text: str, *, dp_init: str = "kind(1.0d0)") -> str:
    """Use a shared kind_mod(sp,dp) when generated code needs kind constants.

    Rewrites generated code to:
    - add module kind_mod with dp parameter
    - replace kind=real64 with kind=dp
    - replace/remove direct iso_fortran_env(real64) USE lines
    """
    lines = text.splitlines(keepends=True)
    if not lines:
        return text

    has_kind_mod = any(re.match(r"^\s*module\s+kind_mod\b", ln, re.IGNORECASE) for ln in lines)
    if has_kind_mod:
        return text

    mod_idx = next((i for i, ln in enumerate(lines) if re.match(r"^\s*module\s+xc2f_mod\b", ln, re.IGNORECASE)), None)
    main_idx = next((i for i, ln in enumerate(lines) if re.match(r"^\s*program\s+main\b", ln, re.IGNORECASE)), None)
    if mod_idx is None and main_idx is None:
        return text
    wants_sp = bool(re.search(r"\bkind\s*=\s*sp\b|_sp\b", text, re.IGNORECASE))
    wants_dp = bool(re.search(r"\bkind\s*=\s*dp\b|_dp\b|\breal64\b", text, re.IGNORECASE))
    if not wants_sp and not wants_dp:
        return text

    # Rewrite kinds.
    lines = [re.sub(r"\bkind\s*=\s*real64\b", "kind=dp", ln) for ln in lines]
    # Rewrite literal suffixes introduced before shared kind module insertion.
    lines = [re.sub(r"(?i)\b([0-9]+(?:\.[0-9]*)?(?:[eEdD][+\-]?[0-9]+)?)_real64\b", r"\1_dp", ln) for ln in lines]

    # Remove direct real64 USE lines.
    use_real64_re = re.compile(r"^\s*use\s*,\s*intrinsic\s*::\s*iso_fortran_env\s*,\s*only\s*:\s*real64\s*$", re.IGNORECASE)
    lines = [ln for ln in lines if not use_real64_re.match(ln.strip())]

    use_syms = []
    if wants_sp:
        use_syms.append("sp")
    if wants_dp:
        use_syms.append("dp")
    use_line = f"use kind_mod, only: {', '.join(use_syms)}\n"

    # Add `use kind_mod, only: ...` in xc2f_mod spec part.
    if mod_idx is not None:
        ins_mod = mod_idx + 1
        if ins_mod <= len(lines):
            lines.insert(ins_mod, use_line)

    # Add `use kind_mod, only: ...` in main program after any use lines.
    main_idx = next((i for i, ln in enumerate(lines) if re.match(r"^\s*program\s+main\b", ln, re.IGNORECASE)), None)
    if main_idx is not None:
        ins_main = main_idx + 1
        while ins_main < len(lines):
            s = lines[ins_main].strip()
            if not s:
                ins_main += 1
                continue
            if re.match(r"^\s*use\b", s, re.IGNORECASE):
                ins_main += 1
                continue
            break
        lines.insert(ins_main, use_line)

    kind_mod_block = [
        "module kind_mod\n",
        "implicit none\n",
        "private\n",
        "public :: sp, dp\n",
        "integer, parameter :: sp = kind(1.0)\n",
        f"integer, parameter :: dp = {dp_init}\n",
        "end module kind_mod\n",
        "\n",
    ]
    lines = kind_mod_block + lines
    return "".join(lines)


def _norm_expr_token(expr: str) -> str:
    s = expr.strip()
    while len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        depth = 0
        ok = True
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    ok = False
                    break
        if not ok:
            break
        s = s[1:-1].strip()
    return re.sub(r"\s+", "", s).lower()


def _remove_arg_style_doc_comments(lines: List[str]) -> List[str]:
    """Drop C-prototype-style doc comments promoted into Fortran.

    Removes lines like:
      ! x: vector
      ! n: extent of x (dimension 1)
    because inline dummy comments are generated separately.
    """
    out: List[str] = []
    arg_cmt_re = re.compile(r"^\s*!\s*[a-z_]\w*\s*:\s*", re.IGNORECASE)
    for ln in lines:
        if arg_cmt_re.match(ln):
            continue
        out.append(ln)
    return out


def _coalesce_simple_declarations_preserve_intent(lines: List[str]) -> List[str]:
    """Coalesce declarations, but keep dummy-arg `intent(...)` lines untouched."""
    out: List[str] = []
    buf: List[str] = []
    intent_re = re.compile(r"\bintent\s*\(", re.IGNORECASE)
    for ln in lines:
        if intent_re.search(ln):
            if buf:
                out.extend(fscan.coalesce_simple_declarations(buf))
                buf = []
            out.append(ln)
        else:
            buf.append(ln)
    if buf:
        out.extend(fscan.coalesce_simple_declarations(buf))
    return out


def _detect_c_real_precision(src_no_comments: str) -> str:
    """Return `single` for float-only C code, otherwise `double`."""
    if re.search(r"\bdouble\b", src_no_comments):
        return "double"
    if re.search(r"\bfloat\b", src_no_comments):
        return "single"
    return "double"


def _normalize_kind_intrinsic_literals(text: str) -> str:
    """Keep `kind(1.0)` / `kind(1.0d0)` free of `_dp` suffixes."""
    return re.sub(r"(?i)\bkind\s*\(\s*([0-9]+(?:\.[0-9]*)?(?:[ed][+\-]?[0-9]+)?)_(?:dp|sp)\s*\)", r"kind(\1)", text)


def _format_transpile_error(exc: Exception, *, source_name: Optional[str] = None) -> str:
    """Return a concise one-line transpile failure description."""
    msg = str(exc).strip()
    name = exc.__class__.__name__
    m = re.match(r"^:(\d+):(\d+):(.*)$", msg)
    if m:
        line_no = int(m.group(1))
        col_no = int(m.group(2))
        rest = m.group(3).strip()
        src_line_no = max(1, line_no - PRELUDE_LINE_COUNT)
        prefix = f"{source_name}:" if source_name else ""
        return f"{name}: {prefix}{src_line_no}:{col_no}: {rest}"
    if not msg:
        return name
    if msg.startswith(f"{name}:"):
        return msg
    return f"{name}: {msg}"


def collapse_int_array_write_implied_do(lines: List[str]) -> List[str]:
    """Collapse specific implied-do integer print pattern to whole-array print.

    Target:
      write (*, "(*(a,i0))") (" ", int(C(i)), i = 1, UB)
    ->
      write (*, "(*(i0, 1x))") int(C)
    when UB matches a prior allocate(C(int(UB))) in the same unit.
    """
    out = list(lines)
    unit_start_re = re.compile(
        r"^\s*(?:[a-z][a-z0-9_()\s=,:]*\s+)?(?:function|subroutine)\b|^\s*program\b",
        re.IGNORECASE,
    )
    unit_end_re = re.compile(r"^\s*end\s+(?:function|subroutine|program)\b", re.IGNORECASE)
    alloc_re = re.compile(
        r"^\s*allocate\s*\(\s*([a-z][a-z0-9_]*)\s*\(\s*(?:int\s*\((.+)\)|(.+))\s*\)\s*(?:,.*)?\)\s*$",
        re.IGNORECASE,
    )
    decl_rank1_re = re.compile(r"^\s*real\b.*\ballocatable\b.*::\s*(.+)$", re.IGNORECASE)
    write_re = re.compile(
        r'^\s*write\s*\(\s*(.+?)\s*,\s*"?\'' r'?\(\*\(a\s*,\s*i0\)\)"?\'' r'?\s*\)\s*'
        r'\(\s*" "\s*,\s*int\s*\(\s*([a-z][a-z0-9_]*)\s*\(\s*([a-z][a-z0-9_]*)\s*\)\s*\)\s*,\s*'
        r'([a-z][a-z0-9_]*)\s*=\s*1\s*,\s*(.+)\)\s*$',
        re.IGNORECASE,
    )

    i = 0
    while i < len(out):
        if not unit_start_re.match(out[i].strip()):
            i += 1
            continue
        u_start = i
        j = i + 1
        while j < len(out) and not unit_end_re.match(out[j].strip()):
            j += 1
        u_end = j

        rank1_names: Set[str] = set()
        alloc_extent: Dict[str, str] = {}
        for k in range(u_start, u_end):
            code, _comment = fscan._split_code_comment(out[k].rstrip("\r\n"))  # type: ignore[attr-defined]
            mdecl = decl_rank1_re.match(code.strip())
            if mdecl:
                for ent in fscan._split_top_level_commas(mdecl.group(1)):  # type: ignore[attr-defined]
                    mname = re.match(r"^\s*([a-z][a-z0-9_]*)\s*\(\s*:\s*\)\s*$", ent.strip(), re.IGNORECASE)
                    if mname:
                        rank1_names.add(mname.group(1).lower())
            ma = alloc_re.match(code.strip())
            if ma:
                ext = ma.group(2) if ma.group(2) is not None else ma.group(3)
                alloc_extent[ma.group(1).lower()] = _norm_expr_token(ext)

        for k in range(u_start, u_end):
            raw = out[k]
            eol = "\r\n" if raw.endswith("\r\n") else ("\n" if raw.endswith("\n") else "\n")
            code, comment = fscan._split_code_comment(raw.rstrip("\r\n"))  # type: ignore[attr-defined]
            m = write_re.match(code.strip())
            if not m:
                continue
            unit_expr, arr, idx1, idx2, ub = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            if idx1.lower() != idx2.lower():
                continue
            arr_l = arr.lower()
            if arr_l not in rank1_names:
                continue
            ub_n = _norm_expr_token(ub)
            ext_n = alloc_extent.get(arr_l)
            if ext_n is None or ub_n != ext_n:
                continue
            indent = re.match(r"^\s*", code).group(0) if code else ""
            out[k] = f'{indent}write ({unit_expr}, "(*(i0, 1x))") int({arr}){comment}{eol}'

        i = u_end + 1
    return out


def rewrite_realloc_assign_patterns(lines: List[str]) -> List[str]:
    """Rewrite `x = int(realloc(x, n))` to allocatable growth via move_alloc."""
    out = list(lines)
    unit_start_re = re.compile(
        r"^\s*(?:[a-z][a-z0-9_()\s=,:]*\s+)?(?:function|subroutine)\b|^\s*program\b",
        re.IGNORECASE,
    )
    unit_end_re = re.compile(r"^\s*end\s+(?:function|subroutine|program)\b", re.IGNORECASE)
    declish_re = re.compile(
        r"^\s*(?:implicit\b|use\b|integer\b|real\b|logical\b|character\b|complex\b|type\b|class\b|procedure\b|save\b|parameter\b|external\b|intrinsic\b|common\b|equivalence\b|dimension\b)",
        re.IGNORECASE,
    )
    asn_re = re.compile(
        r"^\s*([a-z][a-z0-9_]*)\s*=\s*int\s*\(\s*realloc\s*\(\s*([a-z][a-z0-9_]*)\s*,\s*(.+)\)\s*\)\s*$",
        re.IGNORECASE,
    )
    i = 0
    while i < len(out):
        if not unit_start_re.match(out[i].strip()):
            i += 1
            continue
        u_start = i
        j = i + 1
        while j < len(out) and not unit_end_re.match(out[j].strip()):
            j += 1
        u_end = j

        # Collect allocatable declaration type for 1D vars.
        var_type: Dict[str, str] = {}
        for k in range(u_start + 1, u_end):
            code, _comment = fscan._split_code_comment(out[k].rstrip("\r\n"))  # type: ignore[attr-defined]
            if "::" not in code or "allocatable" not in code.lower():
                continue
            lhs, rhs = code.split("::", 1)
            spec = lhs.strip()
            for ent in fscan._split_top_level_commas(rhs):  # type: ignore[attr-defined]
                m = re.match(r"^\s*([a-z][a-z0-9_]*)\s*\(\s*:\s*\)\s*$", ent.strip(), re.IGNORECASE)
                if m:
                    var_type[m.group(1).lower()] = spec

        for k in range(u_start, u_end):
            raw = out[k]
            eol = "\r\n" if raw.endswith("\r\n") else ("\n" if raw.endswith("\n") else "\n")
            code, comment = fscan._split_code_comment(raw.rstrip("\r\n"))  # type: ignore[attr-defined]
            m = asn_re.match(code.strip())
            if not m:
                continue
            lhs = m.group(1)
            arg1 = m.group(2)
            n_expr = m.group(3).strip()
            if lhs.lower() != arg1.lower():
                continue
            if lhs.lower() not in var_type:
                continue
            n_expr = re.sub(r"\s*\*\s*1\s*$", "", n_expr)
            spec = var_type[lhs.lower()]
            indent = re.match(r"^\s*", code).group(0) if code else ""
            tmp = f"{lhs}_tmp"
            repl = [
                f"{indent}block{eol}",
                f"{indent}   {spec} :: {tmp}(:){eol}",
                f"{indent}   allocate({tmp}({n_expr})){eol}",
                f"{indent}   if (allocated({lhs})) {tmp}(1:min(size({lhs}), {n_expr})) = {lhs}(1:min(size({lhs}), {n_expr})){eol}",
                f"{indent}   call move_alloc({tmp}, {lhs}){eol}",
                f"{indent}end block{comment}{eol}",
            ]
            out[k : k + 1] = repl
            u_end += len(repl) - 1
            k += len(repl) - 1
        i = u_end + 1
    return out


def move_decl_comments_to_after_signature(lines: List[str]) -> List[str]:
    """Move comments in declaration section to immediately after unit signature."""
    out = list(lines)
    unit_start_re = re.compile(
        r"^\s*(?:[a-z][a-z0-9_()\s=,:]*\s+)?(?:function|subroutine)\b|^\s*program\b",
        re.IGNORECASE,
    )
    declish_re = re.compile(
        r"^\s*(?:implicit\b|use\b|integer\b|real\b|logical\b|character\b|complex\b|type\b|class\b|procedure\b|save\b|parameter\b|external\b|intrinsic\b|common\b|equivalence\b|dimension\b)",
        re.IGNORECASE,
    )
    i = 0
    while i < len(out):
        if not unit_start_re.match(out[i].strip()):
            i += 1
            continue
        sig_i = i
        j = i + 1
        comment_idx: List[int] = []
        while j < len(out):
            s = out[j].strip()
            if not s:
                j += 1
                continue
            if s.startswith("!"):
                comment_idx.append(j)
                j += 1
                continue
            if declish_re.match(s):
                j += 1
                continue
            break
        if comment_idx:
            comments = [out[k] for k in comment_idx]
            for k in reversed(comment_idx):
                del out[k]
            insert_at = sig_i + 1
            for c in comments:
                out.insert(insert_at, c)
                insert_at += 1
        i = j
    return out


def remove_redundant_final_return(lines: List[str]) -> List[str]:
    """Drop `return` when it appears immediately before `end function`."""
    out = list(lines)
    i = 0
    while i < len(out):
        if out[i].strip().lower().startswith("end function"):
            j = i - 1
            while j >= 0 and not out[j].strip():
                j -= 1
            if j >= 0 and out[j].strip().lower() == "return":
                del out[j]
                i -= 1
        i += 1
    return out


def remove_redundant_final_stop(lines: List[str]) -> List[str]:
    """Drop `stop` when it appears immediately before `end program`."""
    out = list(lines)
    i = 0
    while i < len(out):
        if out[i].strip().lower().startswith("end program"):
            j = i - 1
            while j >= 0 and not out[j].strip():
                j -= 1
            if j >= 0 and out[j].strip().lower() == "stop":
                del out[j]
                i -= 1
        i += 1
    return out


def move_inits_below_early_guard(lines: List[str]) -> List[str]:
    """Move simple initializations below an early validity guard when safe."""
    out = list(lines)
    unit_start_re = re.compile(
        r"^\s*(?:[a-z][a-z0-9_()\s=,:]*\s+)?(?:function|subroutine)\b|^\s*program\b",
        re.IGNORECASE,
    )
    declish_re = re.compile(
        r"^\s*(?:implicit\b|use\b|integer\b|real\b|logical\b|character\b|complex\b|type\b|class\b|procedure\b|save\b|parameter\b|external\b|intrinsic\b|common\b|equivalence\b|dimension\b)",
        re.IGNORECASE,
    )
    simple_init_re = re.compile(r"^\s*([a-z_]\w*)\s*=\s*[^=].*$", re.IGNORECASE)
    if_start_re = re.compile(r"^\s*if\s*\((.*)\)\s*then\s*$", re.IGNORECASE)
    return_re = re.compile(r"^\s*return\s*$", re.IGNORECASE)
    end_if_re = re.compile(r"^\s*end\s*if\b", re.IGNORECASE)
    token_re = re.compile(r"[a-z_]\w*", re.IGNORECASE)

    i = 0
    while i < len(out):
        if not unit_start_re.match(out[i].strip()):
            i += 1
            continue
        j = i + 1
        while j < len(out):
            s = out[j].strip()
            if not s:
                j += 1
                continue
            if s.startswith("!"):
                j += 1
                continue
            if declish_re.match(s):
                j += 1
                continue
            break
        exec_start = j
        init_idx: List[int] = []
        init_names: List[str] = []
        k = exec_start
        while k < len(out):
            s = out[k].strip()
            if not s or s.startswith("!"):
                k += 1
                continue
            m_init = simple_init_re.match(s)
            if not m_init:
                break
            init_idx.append(k)
            init_names.append(m_init.group(1).lower())
            k += 1
        if not init_idx:
            i = exec_start + 1
            continue
        g = k
        while g < len(out) and (not out[g].strip() or out[g].lstrip().startswith("!")):
            g += 1
        if g >= len(out):
            i = g
            continue
        m_if = if_start_re.match(out[g].strip())
        if not m_if:
            i = g + 1
            continue
        cond_text = m_if.group(1)
        depth = 1
        h = g + 1
        saw_return = False
        while h < len(out):
            sh = out[h].strip()
            if if_start_re.match(sh):
                depth += 1
            elif end_if_re.match(sh):
                depth -= 1
                if depth == 0:
                    break
            elif depth == 1 and return_re.match(sh):
                saw_return = True
            h += 1
        if h >= len(out) or not saw_return:
            i = g + 1
            continue
        guard_text = cond_text + "\n" + "".join(out[g + 1 : h])
        guard_tokens = {t.lower() for t in token_re.findall(guard_text)}
        if any(name in guard_tokens for name in init_names):
            i = h + 1
            continue
        moved = [out[idx] for idx in init_idx]
        for idx in reversed(init_idx):
            del out[idx]
        insert_at = h - len(init_idx) + 1
        for line in moved:
            out.insert(insert_at, line)
            insert_at += 1
        i = insert_at
    return out


def collapse_noadvance_integer_print_loops(lines: List[str]) -> List[str]:
    """Collapse common no-advance integer print loops into unlimited-format write."""
    out: List[str] = []
    removed_loop_vars: Set[str] = set()
    i = 0
    re_head = re.compile(
        r'^(?P<indent>\s*)write\(\*,\s*"\(i0,a\)",\s*advance="no"\)\s*(?P<head>[a-z_]\w*)\s*,\s*":"\s*$',
        re.IGNORECASE,
    )
    re_do = re.compile(
        r'^\s*do\s+(?P<iv>[a-z_]\w*)\s*=\s*0\s*,\s*\((?P<nf>[a-z_]\w*)\)\s*-\s*1\s*$',
        re.IGNORECASE,
    )
    re_item = re.compile(
        r'^\s*write\(\*,\s*"\(a,i0\)",\s*advance="no"\)\s*" "\s*,\s*(?P<arr>[a-z_]\w*)\((?P<iv2>[a-z_]\w*)\s*\+\s*1\)\s*$',
        re.IGNORECASE,
    )
    re_enddo = re.compile(r"^\s*end\s*do\s*$", re.IGNORECASE)
    re_nl = re.compile(r"^\s*write\(\*,\*\)\s*$", re.IGNORECASE)
    while i < len(lines):
        m1 = re_head.match(lines[i].rstrip("\n"))
        if m1 and i + 4 < len(lines):
            m2 = re_do.match(lines[i + 1].rstrip("\n"))
            if m2:
                iv = m2.group("iv")
                m3 = re_item.match(lines[i + 2].rstrip("\n"))
                if (
                    m3
                    and m3.group("iv2").lower() == iv.lower()
                    and re_enddo.match(lines[i + 3].rstrip("\n"))
                    and re_nl.match(lines[i + 4].rstrip("\n"))
                ):
                    indent = m1.group("indent")
                    head = m1.group("head")
                    arr = m3.group("arr")
                    out.append(f'{indent}write(*,"(i0,a,*(1x,i0))") {head}, ":", {arr}\n')
                    removed_loop_vars.add(iv.lower())
                    i += 5
                    continue
        out.append(lines[i])
        i += 1
    if not removed_loop_vars:
        return out

    unit_start_re = re.compile(
        r"^\s*(?:[a-z][a-z0-9_()\s=,:]*\s+)?(?:function|subroutine)\b|^\s*program\b",
        re.IGNORECASE,
    )
    unit_end_re = re.compile(r"^\s*end\s+(?:function|subroutine|program)\b", re.IGNORECASE)

    remove_by_line: Dict[int, Set[str]] = {}
    for v in removed_loop_vars:
        pat = re.compile(rf"\b{re.escape(v)}\b", re.IGNORECASE)
        decl_idxs: List[int] = []
        for idx, ln in enumerate(out):
            code, _comment = xunused.split_code_comment(ln.rstrip("\r\n"))
            if "::" in code and pat.search(code):
                decl_idxs.append(idx)
        for didx in decl_idxs:
            s = didx
            while s >= 0:
                code_s, _ = xunused.split_code_comment(out[s].rstrip("\r\n"))
                if unit_start_re.match(code_s.strip()):
                    break
                s -= 1
            if s < 0:
                continue
            t = didx
            while t < len(out):
                code_t, _ = xunused.split_code_comment(out[t].rstrip("\r\n"))
                if unit_end_re.match(code_t.strip()):
                    break
                t += 1
            if t >= len(out):
                continue
            used_elsewhere = False
            for k in range(s, t + 1):
                code_k, _ = xunused.split_code_comment(out[k].rstrip("\r\n"))
                if "::" in code_k and pat.search(code_k):
                    continue
                if pat.search(code_k):
                    used_elsewhere = True
                    break
            if not used_elsewhere:
                remove_by_line.setdefault(didx, set()).add(v)

    if not remove_by_line:
        return out
    cleaned: List[str] = []
    for idx, ln in enumerate(out):
        remove_here = remove_by_line.get(idx)
        if not remove_here:
            cleaned.append(ln)
            continue
        new_ln, _changed = xunused.rewrite_decl_remove_names(ln, remove_here)
        if new_ln is not None:
            cleaned.append(new_ln)
    return cleaned


def apply_dead_store_cleanup(lines: List[str]) -> List[str]:
    """Remove conservative set-but-never-read locals and their safe writes."""
    edits = fscan.find_set_but_never_read_local_edits([ln.rstrip("\r\n") for ln in lines])
    if not edits.decl_remove_by_line and not edits.remove_stmt_lines:
        return lines
    out: List[str] = []
    for idx1, ln in enumerate(lines, start=1):
        if idx1 in edits.remove_stmt_lines:
            continue
        remove_here = edits.decl_remove_by_line.get(idx1)
        if not remove_here:
            out.append(ln)
            continue
        new_ln, _changed = xunused.rewrite_decl_remove_names(ln, remove_here)
        if new_ln is not None:
            out.append(new_ln)
    return out


def add_pure_when_possible(lines: List[str]) -> List[str]:
    """Mark procedures PURE when xpure analyzer classifies them as candidates."""
    parsed = [ln.rstrip("\r\n") for ln in lines]
    sanitized: List[str] = []
    if_then_re = re.compile(r"^\s*(?:else\s+)?if\s*\((.*)\)\s*then\b", re.IGNORECASE)
    for s in parsed:
        m = if_then_re.match(s)
        if not m:
            sanitized.append(s)
            continue
        cond = m.group(1)
        # Avoid xpure's assignment-regex false positives on IF conditions.
        cond2 = cond.replace("==", ".eq.").replace("/=", ".ne.").replace(">=", ".ge.").replace("<=", ".le.")
        sanitized.append(s[: m.start(1)] + cond2 + s[m.end(1) :])
    result = xpure.analyze_lines(sanitized, strict_unknown_calls=False)
    if not result.candidates:
        return lines
    updated = list(lines)
    for proc in result.candidates:
        idx = proc.start - 1
        xpure.apply_decl_edit_at_or_continuation(updated, idx, xpure.add_pure_to_declaration)
    return updated


def inline_single_use_temp_assignments(lines: List[str]) -> List[str]:
    """Inline very-local temp assignments used once in the immediate next statement.

    Conservative scope:
    - assignment form: `name = expr` on one line (no ';' / '&')
    - next nonblank/comment statement uses `name` exactly once
    - no other uses of `name` in the containing unit
    """
    out = list(lines)
    unit_start_re = re.compile(
        r"^\s*(?:[a-z][a-z0-9_()\s=,:]*\s+)?(?:function|subroutine)\b|^\s*program\b",
        re.IGNORECASE,
    )
    unit_end_re = re.compile(r"^\s*end\s+(?:function|subroutine|program)\b", re.IGNORECASE)
    assign_re = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*=\s*(.+)$", re.IGNORECASE)
    ident_re = re.compile(r"[a-z][a-z0-9_]*", re.IGNORECASE)

    unit_ranges: List[Tuple[int, int]] = []
    s: Optional[int] = None
    for i, raw in enumerate(out):
        code = fscan.strip_comment(raw).strip()
        if not code:
            continue
        if s is None and unit_start_re.match(code):
            s = i
            continue
        if s is not None and unit_end_re.match(code):
            unit_ranges.append((s, i))
            s = None
    if s is not None:
        unit_ranges.append((s, len(out) - 1))

    for us, ue in unit_ranges:
        # Never inline TARGET/POINTER entities: their identity matters for
        # pointer association (e.g. structure constructors linking nodes).
        protected: Set[str] = set()
        for k in range(us, ue + 1):
            dcode = fscan.strip_comment(out[k]).strip()
            if "::" in dcode and re.search(r"\btarget\b|\bpointer\b", dcode.split("::", 1)[0], re.IGNORECASE):
                protected.update(fscan.parse_declared_names_from_decl(dcode))
        removed_vars: Set[str] = set()
        i = us
        while i <= ue:
            raw = out[i]
            code, _comment = xunused.split_code_comment(raw.rstrip("\r\n"))
            stmt = code.strip()
            m_as = assign_re.match(stmt)
            if not m_as or ";" in stmt or "&" in stmt:
                i += 1
                continue
            var = m_as.group(1).lower()
            if var in protected:
                i += 1
                continue
            rhs = m_as.group(2).strip()
            if any(tok.group(0).lower() == var for tok in ident_re.finditer(rhs)):
                i += 1
                continue
            # immediate next nonblank/noncomment statement
            j = i + 1
            while j <= ue:
                code_j = fscan.strip_comment(out[j]).strip()
                if code_j:
                    break
                j += 1
            if j > ue:
                i += 1
                continue
            code_j, comment_j = xunused.split_code_comment(out[j].rstrip("\r\n"))
            occ_j = [m for m in ident_re.finditer(code_j) if m.group(0).lower() == var]
            if len(occ_j) != 1:
                i += 1
                continue
            # ensure no other use in unit
            use_count = 0
            for k in range(us, ue + 1):
                code_k, _ = xunused.split_code_comment(out[k].rstrip("\r\n"))
                if k == i:
                    continue
                if "::" in code_k:
                    continue
                use_count += sum(1 for mm in ident_re.finditer(code_k) if mm.group(0).lower() == var)
            if use_count != 1:
                i += 1
                continue
            m0 = occ_j[0]
            # Parenthesize the substituted expression so operator precedence is
            # preserved (notably `(a + bi) * (c + di)` complex expressions).
            new_code_j = f"{code_j[:m0.start()]}({rhs}){code_j[m0.end():]}"
            eol_j = xunused.get_eol(out[j]) or "\n"
            out[j] = f"{new_code_j}{comment_j}{eol_j}"
            # drop assignment line
            out[i] = ""
            removed_vars.add(var)
            i = j + 1

        if removed_vars:
            # remove now-unused declaration entities in this unit
            for k in range(us, ue + 1):
                code_k, _ = xunused.split_code_comment(out[k].rstrip("\r\n"))
                if "::" not in code_k:
                    continue
                present = False
                for v in removed_vars:
                    if any(mm.group(0).lower() == v for mm in ident_re.finditer(code_k)):
                        present = True
                        break
                if not present:
                    continue
                still_used: Set[str] = set()
                for v in removed_vars:
                    for kk in range(us, ue + 1):
                        if kk == k:
                            continue
                        code_kk, _ = xunused.split_code_comment(out[kk].rstrip("\r\n"))
                        if any(mm.group(0).lower() == v for mm in ident_re.finditer(code_kk)):
                            still_used.add(v)
                            break
                to_remove = removed_vars - still_used
                if not to_remove:
                    continue
                new_ln, _changed = xunused.rewrite_decl_remove_names(out[k], to_remove)
                out[k] = "" if new_ln is None else new_ln

    return [ln for ln in out if ln != ""]


def main() -> int:
    ap = argparse.ArgumentParser(description="Partial C to Fortran transpiler")
    ap.add_argument("c_files", type=Path, nargs="+")
    ap.add_argument("--mode", choices=("each", "combined"), default="each", help="Interpret multiple input C files as separate translations (each) or one program (combined)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None, help="Output directory for --mode each")
    ap.add_argument("--tee", action="store_true", help="Print generated Fortran")
    ap.add_argument("--tee-orig", action="store_true", help="Print original C source")
    ap.add_argument("--tee-both", action="store_true", help="Print original C source and generated Fortran")
    ap.add_argument("--raw", action="store_true", help="Emit raw transpilation output (skip optional post-processing)")
    ap.add_argument("--refactor", action="store_true", help="Extract long main-program blocks into module procedures")
    ap.add_argument("--pure", action="store_true", help="Allow promotion of eligible procedures to pure")
    ap.add_argument("--elemental", action="store_true", help="Allow promotion of eligible pure scalar subroutines to elemental")
    ap.add_argument("--array", action="store_true", help="Post-process generated Fortran with xarray.py")
    ap.add_argument("--array-inline", action="store_true", help="With --array, enable xarray inline post-pass")
    ap.add_argument("--inline-temp", action="store_true", help="Post-process generated Fortran with xno_variable.py")
    ap.add_argument("--run", action="store_true", help="Build and run generated Fortran output")
    ap.add_argument("--run-both", action="store_true", help="Build/run original C source and generated Fortran output")
    ap.add_argument("--compile", action="store_true", help="Build generated Fortran output only (no C build or run)")
    ap.add_argument("--compile-c", action="store_true", help="Compile generated Fortran with -c only (no link/run)")
    ap.add_argument("--compile-both", action="store_true", help="Build original C source and generated Fortran output (no run)")
    ap.add_argument("--compile-both-c", action="store_true", help="Compile original C and generated Fortran with -c only (no link/run)")
    ap.add_argument("--run-diff", action="store_true", help="With --run-both, diff stdout/stderr between C and Fortran runs")
    ap.add_argument("--time-both", action="store_true", help="With --run-both, time both executables and report speed ratio")
    ap.add_argument("--maxfail", type=int, default=None, help="Stop after N cases where C builds but generated Fortran does not")
    args = ap.parse_args()
    if args.run_diff or args.time_both:
        args.run_both = True
    action_flags = [
        args.run,
        args.run_both,
        args.compile,
        args.compile_c,
        args.compile_both,
        args.compile_both_c,
    ]
    if sum(bool(flag) for flag in action_flags) > 1:
        print(
            "Use only one of --run, --run-both, --compile, --compile-c, "
            "--compile-both, or --compile-both-c."
        )
        return 2
    if args.out is not None and args.out_dir is not None:
        print("Use only one of --out or --out-dir.")
        return 2
    if args.mode == "combined" and args.out_dir is not None:
        print("--out-dir is only supported with --mode each.")
        return 2
    if args.mode == "each" and len(args.c_files) > 1 and args.out is not None:
        print("--out with multiple input files requires --mode combined or a single input file.")
        return 2
    if args.array_inline:
        args.array = True
    if args.maxfail is not None:
        if args.maxfail < 1:
            print("--maxfail must be >= 1.")
            return 2
        if not (args.run_both or args.compile_both or args.compile_both_c):
            print("--maxfail requires --run-both, --compile-both, or --compile-both-c.")
            return 2
    if args.raw:
        if args.refactor or args.array or args.array_inline or args.inline_temp:
            print("Note: --raw disables --refactor, --array/--array-inline, and --inline-temp.")
        # Raw mode bypasses optional post-processing/refactoring passes.
        args.refactor = False
        args.array = False
        args.array_inline = False
        args.inline_temp = False
    if args.tee_both:
        args.tee_orig = True
        args.tee = True
    if args.elemental:
        args.pure = True
    if args.run_both:
        args.run = True

    def _transpile_text(text: str) -> str:
        fsrc_loc = transpile_c_to_fortran(
            text,
            refactor=args.refactor,
            raw=args.raw,
            pure=args.pure,
            elemental=args.elemental,
        )
        if args.array:
            fsrc_loc = apply_xarray_postprocess(fsrc_loc, inline=args.array_inline)
        if args.inline_temp:
            fsrc_loc = apply_xno_variable_postprocess(fsrc_loc)
        post_lines_loc = fsrc_loc.splitlines(keepends=True)
        post_lines_loc = apply_dead_store_cleanup(post_lines_loc)
        post_lines_loc = fpost.remove_redundant_zero_before_reduction(post_lines_loc)
        post_lines_loc = fpost.remove_pre_overwrite_assignments(post_lines_loc)
        post_lines_loc = fpost.hoist_repeated_size_calls(post_lines_loc, min_uses=3)
        post_lines_loc = fpost.tighten_size_alias_nonpositive_guards(post_lines_loc)
        post_lines_loc = inline_single_use_temp_assignments(post_lines_loc)
        post_lines_loc = fpost.remove_unused_local_declarations(post_lines_loc)
        post_lines_loc = _coalesce_simple_declarations_preserve_intent(post_lines_loc)
        post_lines_loc = fscan.remove_redundant_int_casts(post_lines_loc)
        post_lines_loc = fscan.remove_redundant_real_casts(post_lines_loc)
        post_lines_loc = fscan.suffix_real_literals_with_kind(post_lines_loc, kind_name="dp")
        post_lines_loc = fscan.collapse_single_stmt_if_blocks(post_lines_loc)
        post_lines_loc = fpost.ensure_blank_line_between_module_procedures(post_lines_loc)
        post_lines_loc = _remove_arg_style_doc_comments(post_lines_loc)
        fsrc_loc = _normalize_kind_intrinsic_literals("".join(post_lines_loc))
        if args.array:
            fsrc_loc = apply_xarray_postprocess(fsrc_loc, inline=args.array_inline)
            post_lines_loc = fsrc_loc.splitlines(keepends=True)
            post_lines_loc = apply_dead_store_cleanup(post_lines_loc)
            post_lines_loc = fpost.remove_redundant_zero_before_reduction(post_lines_loc)
            post_lines_loc = fpost.remove_pre_overwrite_assignments(post_lines_loc)
            post_lines_loc = fpost.tighten_size_alias_nonpositive_guards(post_lines_loc)
            post_lines_loc = inline_single_use_temp_assignments(post_lines_loc)
            post_lines_loc = fpost.remove_unused_local_declarations(post_lines_loc)
            post_lines_loc = _coalesce_simple_declarations_preserve_intent(post_lines_loc)
            post_lines_loc = fscan.remove_redundant_int_casts(post_lines_loc)
            post_lines_loc = fscan.remove_redundant_real_casts(post_lines_loc)
            post_lines_loc = fscan.suffix_real_literals_with_kind(post_lines_loc, kind_name="dp")
            post_lines_loc = fscan.collapse_single_stmt_if_blocks(post_lines_loc)
            post_lines_loc = fpost.ensure_blank_line_between_module_procedures(post_lines_loc)
            post_lines_loc = _remove_arg_style_doc_comments(post_lines_loc)
            fsrc_loc = _normalize_kind_intrinsic_literals("".join(post_lines_loc))
        return fsrc_loc

    if args.mode == "combined":
        texts = [p.read_text(encoding="utf-8", errors="ignore") for p in args.c_files]
        text = "\n\n".join(texts)
        try:
            fsrc = _transpile_text(text)
        except Exception as exc:
            print(f"Transpile: FAIL ({_format_transpile_error(exc)})")
            return 1
        fsrc = _prepend_origin_comment(fsrc, args.c_files)
        out_path = args.out if args.out is not None else Path("temp.f90")
        out_path.write_text(fsrc, encoding="utf-8")
        print(f"Wrote {out_path}")
        if args.tee_orig:
            print(text, end="" if text.endswith("\n") else "\n")
        if args.tee:
            print(fsrc, end="")
        orig_ok = False
        orig_out = ""
        orig_err = ""
        orig_build_ok = False
        c_exe = out_path.with_name(f"{out_path.stem}.orig.exe")
        if args.run_both:
            orig_ok, orig_out, orig_err, orig_build_ok = _build_and_run_c_many(
                args.c_files,
                exe_path=c_exe,
                label="original-c",
            )
        elif args.compile_both or args.compile_both_c:
            orig_build_ok = _build_c_many_only(
                args.c_files,
                exe_path=c_exe,
                label="original-c",
                compile_only=bool(args.compile_both_c),
            )
        new_ok = False
        new_out = ""
        new_err = ""
        new_build_ok = False
        f_exe = out_path.with_suffix(".exe")
        if args.run:
            new_ok, new_out, new_err, new_build_ok = _build_and_run(
                out_path,
                compiler="gfortran",
                exe_path=f_exe,
                label="transformed-fortran",
                extra_args=DEFAULT_GFORTRAN_FLAGS,
            )
        elif args.compile_both_c or args.compile_c:
            f_obj = out_path.with_suffix(".o")
            cmd_f = ["gfortran", "-c", str(out_path), *DEFAULT_GFORTRAN_FLAGS, "-o", str(f_obj)]
            new_build_ok = _build_only_cmd(cmd_f, label="transformed-fortran")
        elif args.compile or args.compile_both:
            cmd_f = ["gfortran", str(out_path), *DEFAULT_GFORTRAN_FLAGS, "-o", str(f_exe)]
            new_build_ok = _build_only_cmd(cmd_f, label="transformed-fortran")
        if args.maxfail is not None and orig_build_ok and not new_build_ok:
            print(f"Reached maxfail={args.maxfail} (combined case where C built and Fortran did not).")
        if args.run_diff and args.run_both and orig_ok and new_ok:
            if (orig_out == new_out) and (orig_err == new_err):
                print("Run diff: MATCH")
            else:
                print("Run diff: DIFF")
                old = f"STDOUT:\n{orig_out}\nSTDERR:\n{orig_err}\n"
                new = f"STDOUT:\n{new_out}\nSTDERR:\n{new_err}\n"
                for ln in difflib.unified_diff(
                    old.splitlines(),
                    new.splitlines(),
                    fromfile="original-c",
                    tofile="transformed-fortran",
                    lineterm="",
                ):
                    print(ln)
        if args.time_both and args.run_both and orig_ok and new_ok:
            t_c = _time_executable(c_exe, label="original-c")
            t_f = _time_executable(f_exe, label="transformed-fortran")
            if t_c is not None and t_f is not None and t_c > 0:
                print(f"Time ratio (fortran/c): {t_f / t_c:.3f}")
        actions_ok = _requested_actions_succeeded(
            args,
            original_run_ok=orig_ok,
            original_build_ok=orig_build_ok,
            fortran_run_ok=new_ok,
            fortran_build_ok=new_build_ok,
        )
        return 0 if actions_ok else 1

    # mode each
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
    fail_count = 0
    all_actions_ok = True
    for c_file in args.c_files:
        text = c_file.read_text(encoding="utf-8", errors="ignore")
        try:
            fsrc = _transpile_text(text)
        except Exception as exc:
            print(f"Transpile: FAIL ({_format_transpile_error(exc, source_name=c_file.name)})")
            return 1
        fsrc = _prepend_origin_comment(fsrc, [c_file])
        if args.out_dir is not None:
            out_path = args.out_dir / f"{c_file.stem}.f90"
        elif args.out is not None:
            out_path = args.out
        elif len(args.c_files) == 1:
            out_path = Path("temp.f90")
        else:
            out_path = Path(f"{c_file.stem}.f90")
        out_path.write_text(fsrc, encoding="utf-8")
        print(f"Wrote {out_path}")
        if args.tee_orig:
            print(text, end="" if text.endswith("\n") else "\n")
        if args.tee:
            print(fsrc, end="")
        orig_ok = False
        orig_out = ""
        orig_err = ""
        orig_build_ok = False
        c_exe = c_file.with_suffix(".orig.exe")
        if args.run_both:
            orig_ok, orig_out, orig_err, orig_build_ok = _build_and_run(
                c_file,
                compiler="gcc",
                exe_path=c_exe,
                label="original-c",
                extra_args=["-lm"],
            )
        elif args.compile_both or args.compile_both_c:
            if args.compile_both_c:
                c_obj = c_file.with_suffix(".orig.o")
                cmd_c = ["gcc", "-c", str(c_file), "-o", str(c_obj)]
            else:
                cmd_c = ["gcc", str(c_file), "-lm", "-o", str(c_exe)]
            orig_build_ok = _build_only_cmd(cmd_c, label="original-c")
        new_ok = False
        new_out = ""
        new_err = ""
        new_build_ok = False
        f_exe = out_path.with_suffix(".exe")
        if args.run:
            new_ok, new_out, new_err, new_build_ok = _build_and_run(
                out_path,
                compiler="gfortran",
                exe_path=f_exe,
                label="transformed-fortran",
                extra_args=DEFAULT_GFORTRAN_FLAGS,
            )
        elif args.compile_both_c or args.compile_c:
            f_obj = out_path.with_suffix(".o")
            cmd_f = ["gfortran", "-c", str(out_path), *DEFAULT_GFORTRAN_FLAGS, "-o", str(f_obj)]
            new_build_ok = _build_only_cmd(cmd_f, label="transformed-fortran")
        elif args.compile or args.compile_both:
            cmd_f = ["gfortran", str(out_path), *DEFAULT_GFORTRAN_FLAGS, "-o", str(f_exe)]
            new_build_ok = _build_only_cmd(cmd_f, label="transformed-fortran")
        if args.maxfail is not None and orig_build_ok and not new_build_ok:
            fail_count += 1
            if fail_count >= args.maxfail:
                all_actions_ok = False
                print(f"Stopped at maxfail={args.maxfail} (C built, Fortran did not).")
                break
        if args.run_diff and args.run_both and orig_ok and new_ok:
            if (orig_out == new_out) and (orig_err == new_err):
                print(f"Run diff ({c_file.name}): MATCH")
            else:
                print(f"Run diff ({c_file.name}): DIFF")
                old = f"STDOUT:\n{orig_out}\nSTDERR:\n{orig_err}\n"
                new = f"STDOUT:\n{new_out}\nSTDERR:\n{new_err}\n"
                for ln in difflib.unified_diff(
                    old.splitlines(),
                    new.splitlines(),
                    fromfile="original-c",
                    tofile="transformed-fortran",
                    lineterm="",
                ):
                    print(ln)
        if args.time_both and args.run_both and orig_ok and new_ok:
            t_c = _time_executable(c_exe, label="original-c")
            t_f = _time_executable(f_exe, label="transformed-fortran")
            if t_c is not None and t_f is not None and t_c > 0:
                print(f"Time ratio (fortran/c): {t_f / t_c:.3f}")
        case_actions_ok = _requested_actions_succeeded(
            args,
            original_run_ok=orig_ok,
            original_build_ok=orig_build_ok,
            fortran_run_ok=new_ok,
            fortran_build_ok=new_build_ok,
        )
        all_actions_ok = all_actions_ok and case_actions_ok
    return 0 if all_actions_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
