#!/usr/bin/env python3
"""Step summaries and warning annotations for the CI pipeline (python3 standard library only).

Writes markdown to $GITHUB_STEP_SUMMARY (stdout when unset) and GitHub annotations (::warning) to stdout.
Warnings are only shown, the exit code is always 0.

Usage:
  summary.py flake8 <output file>                         flake8 findings (default format path:line:col: code text)
  summary.py junit <title> <junit xml> [<pytest output>]  test counts, slowest, skipped and failed tests, pytest warnings
  summary.py logs <title> <log file>...                   tracebacks, errors and warnings in server logs
  summary.py images <title> <image>...                    docker image ids and sizes
  summary.py docker-build <title> <build output>...       warnings of docker build (buildkit "WARN:" lines)
  summary.py text <title> <file>                          a file as a code block (e.g. helm output) and its warnings
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter

MAX_ANNOTATIONS = 10    # GitHub shows 10 warnings per step
MAX_LINES = 30          # per list in the summary


def out(md):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(md + "\n")
    else:
        print(md)


def esc(text):
    """Annotation messages: % and newlines need escaping."""
    return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def warn(msg, title=None, file=None, line=None):
    props = []
    if file:
        props.append(f"file={file}")
    if line:
        props.append(f"line={line}")
    if title:
        props.append(f"title={esc(title).replace(',', ';').replace(':', ' -')}")
    print(f"::warning {','.join(props)}::{esc(msg)}" if props else f"::warning::{esc(msg)}")


def read(path):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError as e:
        out(f"* :warning: `{path}`: {e.strerror}")
        return None


def code(lines):
    lines = list(lines)
    more = len(lines) - MAX_LINES
    body = "\n".join(lines[:MAX_LINES]) + (f"\n... {more} more" if more > 0 else "")
    return f"```\n{body}\n```"


def flake8(path):
    text = read(path)
    if text is None:
        return
    found = []
    for line in text.splitlines():
        m = re.match(r"^(.+?):(\d+):(\d+): ([A-Z]+\d+) (.*)$", line)
        if m:
            found.append(m.groups())
    out("### Lint (flake8)\n")
    if not found:
        out("No findings.")
        return
    codes = Counter(f[3] for f in found)
    out(f":warning: **{len(found)} findings** ({', '.join(f'{c} {n}x' for c, n in codes.most_common())})\n")
    out(code(f"{f}:{ln}:{col}: {c} {t}" for f, ln, col, c, t in found))
    for f, ln, _col, c, t in found[:MAX_ANNOTATIONS]:
        warn(f"{c} {t}", title="flake8", file=f, line=ln)


def pytest_warnings(path):
    """The 'warnings summary' section of the pytest output: [(location, warning line)]."""
    text = read(path)
    if not text:
        return []
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    m = re.search(r"=+ warnings summary =+\n(.*?)\n(?:-- Docs:|=+ )", text, re.S)
    if not m:
        return []
    result = []
    for block in m.group(1).strip().split("\n\n"):
        lines = [x for x in block.splitlines() if x.strip()]
        if not lines:
            continue
        # first line: location (or several), then the warning line(s) indented
        location = lines[0].strip()
        warning = next((x.strip() for x in lines[1:] if re.search(r"Warning\b", x)), " ".join(x.strip() for x in lines[1:2]))
        result.append((location, re.sub(r"^\S+:\d+: ", "", warning)))
    return result


def junit(title, path, output=None):
    if not os.path.exists(path):
        out(f"### {title}\n\n:warning: no test report `{path}` (the tests did not run or did not finish)")
        warn(f"no test report {path}", title=title)
        return
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    cases = [tc for s in suites for tc in s.iter("testcase")]
    failed, skipped = [], []
    for tc in cases:
        name = f"{tc.get('classname')}::{tc.get('name')}"
        for child in tc:
            if child.tag in ("failure", "error"):
                failed.append((name, child.tag, (child.get("message") or "").strip()))
            elif child.tag == "skipped":
                skipped.append((name, (child.get("message") or "").strip()))
    total_time = sum(float(s.get("time") or 0) for s in suites)
    passed = len(cases) - len(failed) - len(skipped)
    icon = ":x:" if failed else ":white_check_mark:"
    out(f"### {title}\n")
    out(f"{icon} **{passed} passed, {len(failed)} failed, {len(skipped)} skipped** of {len(cases)} "
        f"in {total_time:.0f} s\n")
    if failed:
        out("| Failed test | Message |\n|---|---|")
        for name, kind, msg in failed[:MAX_LINES]:
            out(f"| `{name}` | {kind}: {msg.splitlines()[0][:200] if msg else ''} |")
        out("")
    if skipped:
        out("| Skipped test | Reason |\n|---|---|")
        for name, msg in skipped[:MAX_LINES]:
            out(f"| `{name}` | {msg[:200]} |")
        out("")
    slow = sorted(cases, key=lambda tc: float(tc.get("time") or 0), reverse=True)[:10]
    if len(cases) > 10:
        out("<details><summary>10 slowest tests</summary>\n\n| Test | Time |\n|---|---|")
        for tc in slow:
            t = float(tc.get("time") or 0)
            out(f"| `{tc.get('classname')}::{tc.get('name')}` | {t:.0f} s |" if t >= 10 else
                f"| `{tc.get('classname')}::{tc.get('name')}` | {t:.2f} s |")
        out("\n</details>\n")
    if output:
        warnings = pytest_warnings(output)
        if warnings:
            counts = Counter(w for _loc, w in warnings)
            out(f":warning: **{len(warnings)} pytest warnings**\n")
            out("| Count | Warning | First location |\n|---|---|---|")
            for w, n in counts.most_common(MAX_LINES):
                loc = next(loc for loc, x in warnings if x == w)
                out(f"| {n} | {w[:200]} | `{loc}` |")
            out("")
            for w, _n in counts.most_common(MAX_ANNOTATIONS):
                loc = next(loc for loc, x in warnings if x == w)
                m = re.match(r"^(\S+?):(\d+)", loc)
                if m and os.path.exists(m.group(1)):
                    warn(w, title=f"{title}: pytest warning", file=m.group(1), line=m.group(2))
                else:
                    warn(f"{loc}: {w}", title=f"{title}: pytest warning")


# log line patterns: name, regex, annotate. The first match counts. "failed" (molior: build-N <type> failed) and
# "Error #" (aptly) are listed but not annotated: the tests provoke failed builds, and aptly logs a missing snapshot
# as "Error #N" before it creates it (normal).
LOG_PATTERNS = [
    ("Traceback", re.compile(r"^Traceback \(most recent call last\)"), True),
    ("SAWarning", re.compile(r"SAWarning"), True),
    ("FATAL", re.compile(r"\bFATAL\b"), True),
    ("ERROR", re.compile(r"\bERROR\b|\bE: "), True),
    ("WARNING", re.compile(r"\bWARNING\b|\bW: |Warning:"), True),
    ("failed", re.compile(r"^molior: build-\d+ \w+ failed"), False),
    ("Error #", re.compile(r"^Error #\d+:"), False),
]


def normalize(line):
    """Group similar lines: numbers, hex ids and quoted names are replaced."""
    line = re.sub(r"^\S+ \S+ UTC \[\d+\] ", "", line)            # postgres prefix
    line = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{12,}\b", "X", line)
    line = re.sub(r"\d+", "N", line)
    return line.strip()[:200]


def logs(title, paths):
    out(f"### {title}\n")
    rows, details, annotations = [], [], []
    for path in paths:
        text = read(path)
        if text is None:
            continue
        lines = text.splitlines()
        counts = Counter()
        examples = {}
        for i, line in enumerate(lines):
            for name, rx, _annotate in LOG_PATTERNS:
                if rx.search(line):
                    counts[name] += 1
                    if name == "Traceback":
                        # the exception is the first line after the stack that is not indented
                        j = i + 1
                        while j < len(lines) and (lines[j].startswith(" ") or not lines[j].strip()):
                            j += 1
                        line = lines[j] if j < len(lines) else line
                    examples.setdefault(name, Counter())[normalize(line)] += 1
                    break
        name = os.path.basename(path)
        rows.append(f"| `{name}` | {len(lines)} | " + " | ".join(str(counts[n]) for n, _rx, _a in LOG_PATTERNS) + " |")
        for kind, _rx, annotate in LOG_PATTERNS:
            if kind in examples:
                details.append(f"**{name}: {kind}** ({counts[kind]})\n")
                details.append(code(f"{n:4}x {line}" for line, n in examples[kind].most_common(MAX_LINES)))
                if annotate:
                    for line, n in examples[kind].most_common(3):
                        annotations.append((f"{name}: {kind} ({n}x): {line}", f"{title}: {kind}"))
    out("| Log | Lines | " + " | ".join(n for n, _rx, _a in LOG_PATTERNS) + " |")
    out("|---|---|" + "---|" * len(LOG_PATTERNS))
    out("\n".join(rows) + "\n")
    if details:
        out("<details><summary>Lines (grouped, numbers replaced by N)</summary>\n")
        out("\n".join(details))
        out("\n</details>\n")
    for msg, t in annotations[:MAX_ANNOTATIONS]:
        warn(msg, title=t)


def images(title, names):
    out(f"### {title}\n")
    out("| Image | Id | Size |\n|---|---|---|")
    for name in names:
        r = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}} {{.Size}}", name],
                           capture_output=True, text=True)
        if r.returncode != 0:
            out(f"| `{name}` | :warning: missing | |")
            warn(f"image {name} missing", title=title)
            continue
        image_id, size = r.stdout.split()
        out(f"| `{name}` | `{image_id.split(':')[-1][:12]}` | {int(size) / 1e6:.0f} MB |")
    out("")


def docker_build(title, paths):
    found = []
    for path in paths:
        text = read(path) or ""
        for line in text.splitlines():
            # buildkit: " 1 warning found ..." and "- <Rule>: <message> (line N)"; legacy: "[WARNING]"
            if re.search(r"WARN(ING)?\b|^\s*-\s+\w+: .*\(line \d+\)", line):
                found.append(f"{os.path.basename(path)}: {line.strip()}")
    out(f"### {title}\n")
    if not found:
        out("No build warnings.")
        return
    out(f":warning: **{len(found)} build warnings**\n")
    out(code(found))
    for line in found[:MAX_ANNOTATIONS]:
        warn(line, title=title)


def text_file(title, path):
    text = read(path)
    if text is None:
        return
    out(f"### {title}\n")
    out(code(text.rstrip().splitlines()))
    for line in text.splitlines():
        if re.search(r"\bwarning\b|\bWARNING\b|^W: |\[WARNING\]", line, re.I):
            warn(line.strip(), title=title)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 0
    cmd, args = argv[1], argv[2:]
    try:
        if cmd == "flake8":
            flake8(*args)
        elif cmd == "junit":
            junit(*args)
        elif cmd == "logs":
            logs(args[0], args[1:])
        elif cmd == "images":
            images(args[0], args[1:])
        elif cmd == "docker-build":
            docker_build(args[0], args[1:])
        elif cmd == "text":
            text_file(*args)
        else:
            print(__doc__)
    except Exception as e:  # never fail the job because of the summary
        print(f"::warning title=summary::{esc(f'summary.py {cmd}: {type(e).__name__}: {e}')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
