#!/usr/bin/env python

"""The files a SystemVerilog front end reads for an RTL file or filelist.

:func:`rtl_input_files` identifies an RTL equivalence proof
(:func:`chipcompiler.tools.lec_result.input_digest`): editing any file it
returns makes the proof stale, so it must not leave one out. A filelist
is read token by token: whitespace separates entries, quotes keep a path
whole, and ``#`` or ``//`` outside quotes starts a comment. Its entries are
sources and the slang options that name files: ``-F`` nests a filelist whose
entries resolve against its own directory, and ``+incdir+`` (``+``-separated
directories) and ``-I``/``--include-directory``/``--isystem`` add include
directories; ``+define+`` names no file. Every source then
brings the files its `` `include `` directives name: every one found in the
including file's directory or an include directory, not only the first, so
the result holds whatever the front end's search order for a quoted or a
``<>`` include (``<>`` searches only ``--isystem`` directories in slang), and
the files those include in turn. Paths resolve as the operating
system opens them, symbolic links followed before ``..`` (``link/..`` is the
parent of the link's target), and every file is listed at its real location:
its own directory and the including file's directory are then those of the
real file, as in kepler-formal's front end. What it cannot place raises
``ValueError`` rather than being left out: any other option, which may read
files (``-f`` resolves against the reading tool's working directory, the
library options ``-v``, ``-y``, ``--libmap`` read sources), an unbalanced
quote, a path with an environment variable (the front end expands it), and
an `` `include `` of a macro or with an argument it cannot read.
"""

import os

_INCLUDE_OPTIONS = frozenset({"-I", "--include-directory", "--isystem"})
_INCDIR = "+incdir+"
_DEFINE = "+define+"
_INCLUDE = "`include"


def rtl_input_files(rtl_path: str, *, filelist: bool) -> list[str]:
    """Every file reading *rtl_path* reads, as real paths in a stable order.

    *filelist* says what *rtl_path* is (its name may have any suffix, or none).
    For a filelist: the filelist, its sources, the files under its include
    directories, and the same for every filelist it nests with ``-F``. For an
    RTL file: the file. Then the files the sources include, transitively.
    Relative entries resolve against the directory of the filelist naming
    them; missing files are kept so a caller can tell, except includes found
    nowhere, which no reader can have read.
    """
    path = os.path.realpath(rtl_path)
    files: list[str] = []
    sources: list[str] = []
    include_dirs: list[str] = []
    if filelist:
        _collect(path, files, sources, include_dirs, set())
    else:
        files.append(path)
        sources.append(path)
    files.extend(_included_files(sources, include_dirs))
    return list(dict.fromkeys(files))


def _collect(
    filelist: str, files: list[str], sources: list[str], include_dirs: list[str], seen: set[str]
) -> None:
    files.append(filelist)
    if filelist in seen or not os.path.isfile(filelist):
        return
    seen.add(filelist)
    base_dir = os.path.dirname(filelist)
    own_include_dirs: list[str] = []
    with open(filelist, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for line_num, line in enumerate(lines, 1):
        where = f"{filelist}:{line_num}"
        tokens = _tokens(line, where)
        # The front end expands $VAR, ${VAR} and $(VAR) in paths.
        if any("$" in token for token in tokens if _names_path(token)):
            raise ValueError(f"{where}: cannot identify a path with an environment variable")
        index = 0
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if token.startswith(_INCDIR):
                own_include_dirs.extend(path for path in _parts(token[len(_INCDIR) :], "+") if path)
            elif token.startswith(_DEFINE):
                continue
            elif token.startswith("+"):
                # Any other plusarg (+libext+, ...) may change what is read.
                raise ValueError(f"{where}: unsupported filelist option {token!r}")
            elif token.startswith("-"):
                option, value = _option(token)
                # Any other option may read files (-f, -v, -y, --libmap, ...).
                if option != "-F" and option not in _INCLUDE_OPTIONS:
                    raise ValueError(f"{where}: unsupported filelist option {option!r}")
                if value is None:
                    if index == len(tokens):
                        raise ValueError(f"{where}: {option!r} needs a value")
                    value = _unquote(tokens[index])
                    index += 1
                if option == "-F":
                    _collect(_real_path(value, base_dir), files, sources, include_dirs, seen)
                else:
                    own_include_dirs.append(value)
            else:
                source = _real_path(_unquote(token), base_dir)
                files.append(source)
                sources.append(source)
    for include_dir in own_include_dirs:
        directory = _real_path(include_dir, base_dir)
        include_dirs.append(directory)
        for root, dirs, names in os.walk(directory):
            dirs.sort()
            files.extend(_real_path(name, root) for name in sorted(names))


def _real_path(path: str, base_dir: str) -> str:
    """The real location of the file *path* (relative to *base_dir*) opens.

    Symbolic links are followed before ``..`` is applied, as the operating
    system does; a lexical normalization would leave ``link/..`` in the
    link's directory.
    """
    return os.path.realpath(os.path.join(base_dir, path))


def _tokens(line: str, where: str) -> list[str]:
    """The entries of a filelist line, quotes kept, comments dropped."""
    tokens: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            quote = "" if char == quote else quote
            current.append(char)
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == "#" or line.startswith("//", index):
            break
        elif char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
        index += 1
    if quote:
        raise ValueError(f"{where}: unbalanced quote")
    if current:
        tokens.append("".join(current))
    return tokens


def _names_path(token: str) -> bool:
    """Whether a filelist entry may name a file (all but non-incdir ``+`` entries)."""
    return not token.startswith("+") or token.startswith(_INCDIR)


def _parts(token: str, separator: str) -> list[str]:
    """*token* split at *separator* outside quotes, the quotes removed."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    for char in token:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
        elif char in "\"'":
            quote = char
        elif char == separator:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _unquote(token: str) -> str:
    return "".join(_parts(token, "\0"))


def _option(token: str) -> tuple[str, str | None]:
    """(option, joined value or None) of ``-Fx``, ``-I=x``, ``-I"x y"``, ``--libdir=x``, ``-F``."""
    if token.startswith("--"):
        name, equals, joined = token.partition("=")
        return name, _unquote(joined) if equals else None
    if len(token) > 2:
        # A short option's joined value may follow an "=" (-I=dir).
        return token[:2], _unquote(token[2:].removeprefix("="))
    return token, None


def _included_files(sources: list[str], include_dirs: list[str]) -> list[str]:
    """The files *sources* (real paths) may include, transitively, in discovery order.

    Each include brings every candidate that exists, which the front end's
    search may have chosen.
    """
    found: list[str] = []
    pending = list(sources)
    visited: set[str] = set()
    while pending:
        source = pending.pop(0)
        if source in visited or not os.path.isfile(source):
            continue
        visited.add(source)
        with open(source, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        for name in include_targets(text, source):
            for directory in (os.path.dirname(source), *include_dirs):
                candidate = _real_path(name, directory)
                if os.path.isfile(candidate):
                    found.append(candidate)
                    pending.append(candidate)
    return found


def include_targets(text: str, where: str) -> list[str]:
    """The file names of *text*'s `` `include `` directives, in order.

    Comments, string literals and escaped identifiers (``\\name`` up to
    whitespace) are skipped, so a directive may follow a comment or other code
    on its line, and one inside a comment or string is none. Raises
    ``ValueError`` for an `` `include `` of a macro or with an argument that is
    no quoted or ``<>`` file name.
    """
    targets: list[str] = []
    index, end = 0, len(text)
    while index < end:
        if text.startswith("//", index):
            newline = text.find("\n", index)
            index = end if newline < 0 else newline
        elif text.startswith("/*", index):
            index = _block_comment_end(text, index)
        elif text[index] == '"':
            index = _string_end(text, index)
        elif text[index] == "\\":
            # An escaped identifier holds any characters up to whitespace.
            index += 1
            while index < end and not text[index].isspace():
                index += 1
        elif text.startswith(_INCLUDE, index) and not _is_identifier_char(
            text, index + len(_INCLUDE)
        ):
            index, target = _include_target(text, index + len(_INCLUDE), where)
            if target:
                targets.append(target)
        else:
            index += 1
    return targets


def _include_target(text: str, index: int, where: str) -> tuple[int, str]:
    """(index after, file name) of the directive argument at *index*."""
    end = len(text)
    while index < end:
        if text[index] != "\n" and text[index].isspace():
            index += 1
        elif text.startswith("/*", index):
            index = _block_comment_end(text, index)
        else:
            break
    if index < end and text[index] in '"<':
        close = text.find('"' if text[index] == '"' else ">", index + 1)
        if close >= 0:
            return close + 1, text[index + 1 : close]
    if index < end and text[index] == "`":
        raise ValueError(f"{where}: cannot identify an `include of a macro")
    raise ValueError(f"{where}: cannot identify an `include argument")


def _block_comment_end(text: str, index: int) -> int:
    close = text.find("*/", index + 2)
    return len(text) if close < 0 else close + 2


def _string_end(text: str, index: int) -> int:
    """The index after the string literal opening at *index* (ends at a newline)."""
    index += 1
    while index < len(text) and text[index] not in '"\n':
        index += 2 if text[index] == "\\" else 1
    return index + 1


def _is_identifier_char(text: str, index: int) -> bool:
    return index < len(text) and (text[index].isalnum() or text[index] in "_$")
