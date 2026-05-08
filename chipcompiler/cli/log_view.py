import enum
import re
import sys

from chipcompiler.cli.pretty import BOLD, DIM, RED, YELLOW, BLUE, CYAN, RESET, style
from chipcompiler.cli.render import _plain_value


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

_KIND_LABEL = {
    LineKind.ERROR: "error",
    LineKind.WARNING: "warn ",
    LineKind.INFO: "info ",
    LineKind.TRACEBACK: "trace",
    LineKind.SECTION: "-----",
    LineKind.PLAIN: "     ",
}

_KIND_COLOR = {
    LineKind.ERROR: RED,
    LineKind.WARNING: YELLOW,
    LineKind.TRACEBACK: YELLOW,
    LineKind.INFO: BLUE,
    LineKind.SECTION: CYAN,
}


def render_log_pretty(
    step: str,
    source: str,
    lines: list[str],
    inspect_cmd: str,
    file=None,
    color: bool = True,
) -> None:
    target = file or sys.stdout
    annotated = annotate_log_lines(lines)

    log_tag = style("[log]", BOLD, color)
    source_label = f"  {style('source:', DIM, color)}" if color else "  source:"
    target.write(f"{log_tag} step={step}\n")
    target.write(f"{source_label} {source}\n")

    for ll in annotated:
        label = _KIND_LABEL[ll.kind]
        if color and ll.kind in _KIND_COLOR:
            code = _KIND_COLOR[ll.kind]
            if ll.kind == LineKind.ERROR:
                target.write(f"  {code}{label} {ll.text}{RESET}\n")
            else:
                target.write(f"  {code}{label}{RESET} {ll.text}\n")
        else:
            target.write(f"  {label} {ll.text}\n")

    inspect_label = f"  {style('inspect:', DIM, color)}" if color else "  inspect:"
    target.write(f"{inspect_label} {inspect_cmd}\n")


def _render_plain_record(rec, target):
    parts = []
    for key in ("step", "source", "line_no", "kind", "line", "inspect_cmd"):
        parts.append(f"{key}={_plain_value(rec.get(key, ''))}")
    target.write(" ".join(parts) + "\n")


def render_log_plain(
    step: str,
    source: str,
    lines: list[str],
    inspect_cmd: str,
    file=None,
) -> None:
    target = file or sys.stdout
    records = build_log_records(step, source, lines, inspect_cmd)
    for rec in records:
        _render_plain_record(rec, target)


def render_log_records_plain(records, file=None) -> None:
    target = file or sys.stdout
    for rec in records:
        _render_plain_record(rec, target)


def tail_lines_for_log(path: str, max_lines: int = 10) -> list[str]:
    """Return up to max_lines non-empty sanitized lines from the end of a log file."""
    try:
        with open(path, errors="replace") as f:
            raw = f.read().splitlines()
    except OSError:
        return []

    from chipcompiler.cli.progress import sanitize_log_line
    sanitized = [sanitize_log_line(line) for line in raw]
    non_empty = [line for line in sanitized if line]
    return non_empty[-max_lines:]


def render_log_listing_pretty(
    records: list[dict],
    file=None,
    color: bool = True,
    tail_map: dict | None = None,
) -> None:
    target = file or sys.stdout

    log_tag = style("[logs]", BOLD, color)
    target.write(f"{log_tag}\n")

    for rec in records:
        step = rec.get("step", "")
        source = rec.get("source") or rec.get("log", "")
        inspect = rec.get("inspect_cmd") or rec.get("inspect", "")

        if step:
            step_label = f"  {style(step, CYAN, color)}" if color else f"  {step}"
        else:
            step_label = ""

        target.write(f"{step_label}  {source}\n")

        if tail_map and source in tail_map:
            tail_lines = tail_map[source]
            if tail_lines:
                tail_label = f"  {style('tail:', DIM, color)}" if color else "  tail:"
                for tl in tail_lines:
                    target.write(f"{tail_label} {tl}\n")

        inspect_label = f"  {style('inspect:', DIM, color)}" if color else "  inspect:"
        target.write(f"{inspect_label} {inspect}\n")


# --- Context extraction ---


def extract_error_context(lines: list[str], max_lines: int = 50) -> list:
    """Extract at most max_lines log lines around the failure anchor.

    Anchor priority: last error > last traceback > last \"failed\" > last non-empty.
    """
    if not lines:
        return []

    annotated = annotate_log_lines(lines)
    total = len(annotated)

    anchor_idx = _find_context_anchor(annotated)

    if total <= max_lines:
        return annotated

    half = max_lines // 2
    start = max(0, anchor_idx - half)
    end = min(total, start + max_lines)
    if end - start < max_lines:
        start = max(0, end - max_lines)

    return annotated[start:end]


def _find_context_anchor(annotated):
    # Priority 1: last error line
    for i in range(len(annotated) - 1, -1, -1):
        if annotated[i].kind == LineKind.ERROR:
            return i

    # Priority 2: last traceback line
    for i in range(len(annotated) - 1, -1, -1):
        if annotated[i].kind == LineKind.TRACEBACK:
            return i

    # Priority 3: last line containing "failed"
    for i in range(len(annotated) - 1, -1, -1):
        if "failed" in annotated[i].text.lower():
            return i

    # Priority 4: last non-empty line
    for i in range(len(annotated) - 1, -1, -1):
        if annotated[i].text.strip():
            return i

    return len(annotated) - 1
