import enum
import re


class LineKind(enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    TRACEBACK = "traceback"
    SECTION = "section"
    PLAIN = "plain"


_TRACEBACK_HEADER = "Traceback (most recent call last):"

_ERROR_RE = re.compile(r"error", re.IGNORECASE)
_WARNING_RE = re.compile(r"warn(?:ing)?", re.IGNORECASE)
_INFO_RE = re.compile(r"^(?:INFO(?:\s*:|\s*\]|:root:)|\[INFO\s*\])")
_SECTION_RE = re.compile(r"^[-=]{3,}$")
_EXCEPTION_RE = re.compile(
    r"^[A-Za-z_][\w.]*:\s"
    r"|^[A-Za-z_]\w*(?:Error|Exception|Warning|Interrupt|Exit|Iteration)$"
    r"|^(?:KeyboardInterrupt|SystemExit|StopIteration|GeneratorExit)$"
)


def classify_line(line: str, in_traceback: bool = False) -> LineKind:
    if line.strip() == _TRACEBACK_HEADER:
        return LineKind.TRACEBACK
    if in_traceback:
        stripped = line.strip()
        if not stripped:
            return LineKind.PLAIN
        if line.startswith("  ") or line.startswith("\t"):
            return LineKind.TRACEBACK
        if _EXCEPTION_RE.match(stripped):
            return LineKind.ERROR
        if _ERROR_RE.search(stripped):
            return LineKind.ERROR
        return LineKind.PLAIN
    if _SECTION_RE.match(line.strip()):
        return LineKind.SECTION
    if _INFO_RE.match(line):
        return LineKind.INFO
    if _WARNING_RE.search(line):
        return LineKind.WARNING
    if _ERROR_RE.search(line):
        return LineKind.ERROR
    return LineKind.PLAIN


class LogLine:
    __slots__ = ("line_no", "kind", "text")

    def __init__(self, line_no: int, kind: LineKind, text: str):
        self.line_no = line_no
        self.kind = kind
        self.text = text

    def __eq__(self, other):
        if not isinstance(other, LogLine):
            return NotImplemented
        return (self.line_no, self.kind, self.text) == (other.line_no, other.kind, other.text)

    def __repr__(self):
        return f"LogLine({self.line_no!r}, {self.kind!r}, {self.text!r})"


def annotate_log_lines(lines: list[str]) -> list[LogLine]:
    result = []
    in_traceback = False
    for i, text in enumerate(lines):
        kind = classify_line(text, in_traceback)
        if kind == LineKind.TRACEBACK and text.strip() == _TRACEBACK_HEADER:
            in_traceback = True
        elif in_traceback and kind == LineKind.ERROR:
            in_traceback = False
        elif in_traceback and kind == LineKind.PLAIN and not text.startswith("  ") and not text.startswith("\t") and text.strip():
            in_traceback = False
        result.append(LogLine(line_no=i + 1, kind=kind, text=text))
    return result


def build_log_records(
    step: str,
    source: str,
    lines: list[str],
    inspect_cmd: str,
) -> list[dict]:
    annotated = annotate_log_lines(lines)
    records = []
    for ll in annotated:
        records.append({
            "step": step,
            "source": source,
            "line_no": ll.line_no,
            "kind": ll.kind.value,
            "line": ll.text,
            "inspect_cmd": inspect_cmd,
        })
    return records


# --- Pretty rendering ---

_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_CYAN = "\x1b[36m"
_BLUE = "\x1b[34m"
_RESET = "\x1b[0m"

_KIND_LABEL = {
    LineKind.ERROR: "error",
    LineKind.WARNING: "warn ",
    LineKind.INFO: "info ",
    LineKind.TRACEBACK: "trace",
    LineKind.SECTION: "-----",
    LineKind.PLAIN: "     ",
}

_KIND_COLOR = {
    LineKind.ERROR: _RED,
    LineKind.WARNING: _YELLOW,
    LineKind.TRACEBACK: _YELLOW,
    LineKind.INFO: _BLUE,
    LineKind.SECTION: _CYAN,
}


def render_log_pretty(
    step: str,
    source: str,
    lines: list[str],
    inspect_cmd: str,
    file=None,
    color: bool = True,
) -> None:
    import sys
    target = file or sys.stdout
    annotated = annotate_log_lines(lines)

    if color:
        target.write(f"{_BOLD}[log]{_RESET} step={step}\n")
        target.write(f"  {_DIM}source:{_RESET} {source}\n")
    else:
        target.write(f"[log] step={step}\n")
        target.write(f"  source: {source}\n")

    for ll in annotated:
        label = _KIND_LABEL[ll.kind]
        if color and ll.kind in _KIND_COLOR:
            code = _KIND_COLOR[ll.kind]
            target.write(f"  {code}{label}{_RESET} {ll.text}\n")
        else:
            target.write(f"  {label} {ll.text}\n")

    if color:
        target.write(f"  {_DIM}inspect:{_RESET} {inspect_cmd}\n")
    else:
        target.write(f"  inspect: {inspect_cmd}\n")


def _format_value(value) -> str:
    s = str(value)
    if any(c.isspace() for c in s) or '\\' in s or '"' in s or '=' in s:
        escaped = s.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _render_plain_record(rec, target):
    parts = []
    for key in ("step", "source", "line_no", "kind", "line", "inspect_cmd"):
        parts.append(f"{key}={_format_value(rec.get(key, ''))}")
    target.write(" ".join(parts) + "\n")


def render_log_plain(
    step: str,
    source: str,
    lines: list[str],
    inspect_cmd: str,
    file=None,
) -> None:
    import sys
    target = file or sys.stdout
    records = build_log_records(step, source, lines, inspect_cmd)
    for rec in records:
        _render_plain_record(rec, target)


def render_log_records_plain(records, file=None) -> None:
    import sys
    target = file or sys.stdout
    for rec in records:
        _render_plain_record(rec, target)


def render_log_listing_pretty(
    records: list[dict],
    file=None,
    color: bool = True,
) -> None:
    import sys
    target = file or sys.stdout

    if color:
        target.write(f"{_BOLD}[logs]{_RESET}\n")
    else:
        target.write("[logs]\n")

    for rec in records:
        step = rec.get("step", "")
        source = rec.get("source") or rec.get("log", "")
        inspect = rec.get("inspect_cmd") or rec.get("inspect", "")

        if step:
            if color:
                target.write(f"  {_CYAN}{step}{_RESET}  {source}\n")
                target.write(f"  {_DIM}inspect:{_RESET} {inspect}\n")
            else:
                target.write(f"  {step}  {source}\n")
                target.write(f"  inspect: {inspect}\n")
        else:
            if color:
                target.write(f"  {source}\n")
                target.write(f"  {_DIM}inspect:{_RESET} {inspect}\n")
            else:
                target.write(f"  {source}\n")
                target.write(f"  inspect: {inspect}\n")
