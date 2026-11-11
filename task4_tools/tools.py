"""Workspace-confined tools exposed to the Task 4 language model."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from tool_contract import (
    DEFAULT_TIMEOUT_S,
    MAX_LIST_ENTRIES,
    MAX_OUTPUT_CHARS,
    MAX_READ_LINES,
    MAX_SEARCH_RESULTS,
    ToolRegistryBase,
    ToolResult,
)


_TOOL_DEFINITIONS = [
    {
        "name": "list_files",
        "description": "List relative file paths under a workspace directory.",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative directory (default '.')"},
            "pattern": {"type": "string", "description": "Optional glob relative to the directory"},
        },
        "required": [],
    },
    {
        "name": "read_file",
        "description": "Read numbered lines from a workspace file.",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
    },
    {
        "name": "search_code",
        "description": "Search UTF-8 workspace files using a regular expression.",
        "properties": {
            "pattern": {"type": "string"},
            "glob": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_RESULTS},
        },
        "required": ["pattern"],
    },
    {
        "name": "run_tests",
        "description": "Run pytest in the workspace and return a structured summary.",
        "properties": {
            "target": {"type": "string", "description": "Optional tests/test_x.py or tests/test_x.py::test_name"},
        },
        "required": [],
    },
    {
        "name": "run_cli",
        "description": "Run the tinyledger report, balances, or settle CLI on a workspace CSV file.",
        "properties": {"args": {"type": "array", "items": {"type": "string"}, "minItems": 2}},
        "required": ["args"],
    },
    {
        "name": "edit_file",
        "description": "Replace one unique exact string in an existing file below src/.",
        "properties": {
            "path": {"type": "string"},
            "old_str": {"type": "string", "minLength": 1},
            "new_str": {"type": "string"},
        },
        "required": ["path", "old_str", "new_str"],
    },
]


class ToolRegistry(ToolRegistryBase):
    """Implement the contract while constraining all file/process access to a workspace."""

    def __init__(self, workspace: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        super().__init__(workspace, timeout_s)
        self._root = self.workspace.resolve(strict=True)
        if not self._root.is_dir():
            raise ValueError("workspace must be a directory")
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive number")

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": {
                        "type": "object",
                        "properties": spec["properties"],
                        "required": list(spec["required"]),
                        "additionalProperties": False,
                    },
                },
            }
            for spec in _TOOL_DEFINITIONS
        ]

    def execute(self, name: str, arguments: str) -> ToolResult:
        """Validate and execute one call. Never leak exceptions to the caller."""
        try:
            if not isinstance(name, str) or not isinstance(arguments, str):
                return ToolResult(ok=False, error="Tool name and arguments must be strings.")
            specs = {spec["name"]: spec for spec in _TOOL_DEFINITIONS}
            spec = specs.get(name)
            if spec is None:
                return ToolResult(ok=False, error=f"Unknown tool: {name!r}.")
            try:
                values = json.loads(arguments)
            except (json.JSONDecodeError, TypeError, ValueError):
                return ToolResult(ok=False, error="Arguments must be a valid JSON object.")
            if not isinstance(values, dict):
                return ToolResult(ok=False, error="Arguments must be a JSON object.")
            error = self._validate_arguments(spec, values)
            if error:
                return ToolResult(ok=False, error=error)
            handler = getattr(self, f"_tool_{name}")
            result = handler(values)
            return self._bound(result)
        except ValueError as exc:
            return self._bound(ToolResult(ok=False, error=str(exc)))
        except Exception as exc:
            # Do not include arbitrary exception reprs or file content in model-visible errors.
            return self._bound(ToolResult(ok=False, error=f"Tool failed safely ({type(exc).__name__})."))

    @staticmethod
    def _validate_arguments(spec: dict, values: dict) -> str | None:
        properties = spec["properties"]
        extra = sorted(set(values) - set(properties))
        if extra:
            return f"Unexpected argument(s): {', '.join(extra)}."
        missing = [key for key in spec["required"] if key not in values]
        if missing:
            return f"Missing required argument(s): {', '.join(missing)}."
        for key, value in values.items():
            rule = properties[key]
            kind = rule["type"]
            valid = (
                isinstance(value, str) if kind == "string" else
                (isinstance(value, int) and not isinstance(value, bool)) if kind == "integer" else
                isinstance(value, list) and all(isinstance(item, str) for item in value) if kind == "array" else
                False
            )
            if not valid:
                return f"Argument {key!r} must be {kind}."
            if kind == "string" and rule.get("minLength", 0) > len(value):
                return f"Argument {key!r} must not be empty."
            if kind == "integer":
                if value < rule.get("minimum", value) or value > rule.get("maximum", value):
                    return f"Argument {key!r} is outside its allowed range."
            if kind == "array" and len(value) < rule.get("minItems", 0):
                return f"Argument {key!r} must contain at least {rule['minItems']} items."
        return None

    def _resolve(self, value: str, *, must_exist: bool = True) -> Path:
        if not value or "\x00" in value:
            raise ValueError("path must be a non-empty workspace-relative path")
        candidate = Path(value)
        if candidate.is_absolute() or candidate.drive or re.match(r"^[a-zA-Z]:", value):
            raise ValueError("absolute paths are not allowed")
        # Treat both separator styles as separators on Windows and reject traversal explicitly.
        parts = value.replace("\\", "/").split("/")
        if any(part == ".." for part in parts):
            raise ValueError("parent-directory traversal is not allowed")
        resolved = (self._root / candidate).resolve(strict=must_exist)
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("path resolves outside the workspace") from exc
        return resolved

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _tool_list_files(self, args: dict) -> ToolResult:
        base = self._resolve(args.get("path", "."))
        if not base.is_dir():
            return ToolResult(ok=False, error="path must name a directory")
        pattern = args.get("pattern", "**/*")
        if self._unsafe_glob(pattern):
            return ToolResult(ok=False, error="pattern must be relative and may not traverse outside its directory")
        paths = []
        for entry in base.glob(pattern):
            if any(part in {".git", "__pycache__", ".pytest_cache"} for part in entry.relative_to(base).parts):
                continue
            try:
                resolved = entry.resolve(strict=True)
                resolved.relative_to(self._root)
            except (OSError, ValueError, RuntimeError):
                continue
            if resolved.is_file():
                paths.append(self._relative(resolved))
        paths.sort()
        truncated = len(paths) > MAX_LIST_ENTRIES
        return ToolResult(ok=True, output=paths[:MAX_LIST_ENTRIES], truncated=truncated)

    def _tool_read_file(self, args: dict) -> ToolResult:
        path = self._resolve(args["path"])
        if not path.is_file():
            return ToolResult(ok=False, error="path must name a file")
        lines = path.read_text(encoding="utf-8").splitlines()
        start = args.get("start_line", 1)
        end = args.get("end_line", len(lines))
        if end < start:
            return ToolResult(ok=False, error="end_line must be greater than or equal to start_line")
        requested_end = min(end, start + MAX_READ_LINES - 1)
        selected = lines[start - 1:requested_end]
        numbered = "\n".join(f"{line_no}: {line}" for line_no, line in enumerate(selected, start=start))
        return ToolResult(ok=True, output=numbered, truncated=end > requested_end or end > len(lines))

    def _tool_search_code(self, args: dict) -> ToolResult:
        try:
            matcher = re.compile(args["pattern"])
        except re.error as exc:
            return ToolResult(ok=False, error=f"Invalid regular expression: {exc.msg}")
        limit = args.get("max_results", MAX_SEARCH_RESULTS)
        glob = args.get("glob", "**/*")
        if self._unsafe_glob(glob):
            return ToolResult(ok=False, error="glob must be relative and may not traverse outside the workspace")
        matches: list[str] = []
        candidates = sorted(self._root.glob(glob))
        clipped = False
        for candidate in candidates:
            try:
                if any(part in {".git", "__pycache__", ".pytest_cache"} for part in candidate.relative_to(self._root).parts):
                    continue
            except ValueError:
                continue
            try:
                path = candidate.resolve(strict=True)
                path.relative_to(self._root)
            except (OSError, ValueError, RuntimeError):
                continue
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8") as stream:
                    for line_no, line in enumerate(stream, start=1):
                        if matcher.search(line):
                            matches.append(f"{self._relative(path)}:{line_no}: {line.rstrip()}" )
                            if len(matches) >= limit:
                                clipped = True
                                break
            except (UnicodeError, OSError):
                continue
            if clipped:
                break
        return ToolResult(ok=True, output="\n".join(matches), truncated=clipped)

    def _minimal_env(self, *, pythonpath: str) -> dict[str, str]:
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP") if key in os.environ}
        python_dir = str(Path(sys.executable).resolve().parent)
        system_dir = str(Path(env.get("SYSTEMROOT", r"C:\Windows")) / "System32")
        env["PATH"] = os.pathsep.join(dict.fromkeys((python_dir, system_dir)))
        env.update({"PYTHONPATH": pythonpath, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
        return env

    def _run_process(self, command: list[str], *, pythonpath: str) -> subprocess.CompletedProcess[str] | ToolResult:
        try:
            return subprocess.run(
                command,
                cwd=self._root,
                env=self._minimal_env(pythonpath=pythonpath),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ToolResult(ok=False, error=f"Process timed out after {self.timeout_s:g} seconds.",
                              output={"stdout": self._text(exc.stdout), "stderr": self._text(exc.stderr)})
        except (OSError, ValueError):
            return ToolResult(ok=False, error="Could not start the approved workspace process.")

    @staticmethod
    def _text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _tool_run_tests(self, args: dict) -> ToolResult:
        target = args.get("target")
        command = [sys.executable, "-m", "pytest", "-q"]
        command.extend(["-p", "no:cacheprovider"])
        if target is not None:
            match = re.fullmatch(r"(tests/[A-Za-z0-9_.-]+\.py)(?:::(test_[A-Za-z0-9_]+))?", target)
            if not match:
                return ToolResult(ok=False, error="target must be a tests/test_x.py path, optionally followed by ::test_name")
            target_path = self._resolve(match.group(1))
            if not target_path.is_file():
                return ToolResult(ok=False, error="test target does not exist")
            command.extend([match.group(1) + (("::" + match.group(2)) if match.group(2) else "")])
        report_handle = tempfile.NamedTemporaryFile(prefix=".pytest-report-", suffix=".xml", dir=self._root, delete=False)
        report = Path(report_handle.name)
        report_handle.close()
        try:
            proc = self._run_process(command + [f"--junitxml={report}"], pythonpath=str(self._root / "src"))
            if isinstance(proc, ToolResult):
                return proc
            summary = {"passed": 0, "failed": 0, "failing_tests": [], "tracebacks": []}
            if report.is_file():
                try:
                    suite = ET.parse(report).getroot()
                    suites = [suite] if suite.tag == "testsuite" else list(suite.iter("testsuite"))
                    for item in suites:
                        summary["passed"] += int(item.get("tests", "0")) - int(item.get("failures", "0")) - int(item.get("errors", "0")) - int(item.get("skipped", "0"))
                        summary["failed"] += int(item.get("failures", "0")) + int(item.get("errors", "0"))
                    for case in suite.iter("testcase"):
                        failure = case.find("failure")
                        if failure is None:
                            failure = case.find("error")
                        if failure is not None:
                            summary["failing_tests"].append("::".join(x for x in (case.get("classname"), case.get("name")) if x))
                            summary["tracebacks"].append((failure.get("message", "") + "\n" + (failure.text or ""))[:1200])
                except (ET.ParseError, ValueError):
                    pass
            summary["exit_code"] = proc.returncode
            if not report.is_file() and proc.returncode != 0:
                summary["tracebacks"] = [proc.stderr[-1200:] or proc.stdout[-1200:]]
            return ToolResult(ok=True, output=summary)
        finally:
            report.unlink(missing_ok=True)

    def _tool_run_cli(self, args: dict) -> ToolResult:
        cli_args = args["args"]
        if len(cli_args) < 2 or cli_args[0] not in {"report", "balances", "settle"}:
            return ToolResult(ok=False, error="args must start with report, balances, or settle and a CSV path")
        try:
            csv_path = self._resolve(cli_args[1])
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        if not csv_path.is_file() or csv_path.suffix.lower() != ".csv":
            return ToolResult(ok=False, error="CSV argument must name an existing workspace .csv file")
        remaining = cli_args[2:]
        if remaining and (len(remaining) != 2 or remaining[0] != "--month" or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", remaining[1])):
            return ToolResult(ok=False, error="Only an optional --month YYYY-MM argument is allowed")
        command = [sys.executable, "-m", "tinyledger", cli_args[0], cli_args[1], *remaining]
        proc = self._run_process(command, pythonpath=str(self._root / "src"))
        if isinstance(proc, ToolResult):
            return proc
        return ToolResult(ok=True, output={"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})

    def _tool_edit_file(self, args: dict) -> ToolResult:
        raw_path = args["path"].replace("\\", "/")
        if not raw_path.startswith("src/"):
            return ToolResult(ok=False, error="edit_file may only modify existing files below src/")
        path = self._resolve(raw_path)
        try:
            path.relative_to((self._root / "src").resolve(strict=True))
        except ValueError:
            return ToolResult(ok=False, error="resolved edit target must remain below src/")
        if not path.is_file():
            return ToolResult(ok=False, error="edit_file requires an existing file below src/")
        old = args["old_str"]
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count != 1:
            return ToolResult(ok=False, error=f"old_str must match exactly once (found {count})")
        updated = text.replace(old, args["new_str"], 1)
        path.write_text(updated, encoding="utf-8", newline="")
        import difflib

        diff = "".join(difflib.unified_diff(text.splitlines(keepends=True), updated.splitlines(keepends=True),
                                           fromfile=self._relative(path), tofile=self._relative(path)))
        return ToolResult(ok=True, output=diff)

    @staticmethod
    def _unsafe_glob(pattern: str) -> bool:
        candidate = Path(pattern)
        return (
            candidate.is_absolute()
            or bool(candidate.drive)
            or "\x00" in pattern
            or any(part == ".." for part in pattern.replace("\\", "/").split("/"))
        )

    @staticmethod
    def _shrink(value: Any) -> Any:
        if isinstance(value, str):
            return value[: max(0, len(value) // 2)] + "…[truncated]"
        if isinstance(value, list):
            if len(value) > 1:
                return value[: max(1, len(value) // 2)]
            if value:
                return [ToolRegistry._shrink(value[0])]
            return value
        if isinstance(value, dict):
            for key in reversed(list(value)):
                if isinstance(value[key], (str, list, dict)) and value[key]:
                    smaller = dict(value)
                    smaller[key] = ToolRegistry._shrink(value[key])
                    return smaller
            return value
        return value

    @staticmethod
    def _bound(result: ToolResult) -> ToolResult:
        if not isinstance(result, ToolResult):
            result = ToolResult(ok=False, error="Tool returned an invalid result.")
        if not result.ok and not isinstance(result.error, str):
            result.error = "Tool failed."
        try:
            serialized = result.to_content()
        except (TypeError, ValueError):
            result = ToolResult(ok=False, error="Tool result was not JSON serializable.")
            serialized = result.to_content()
        if len(serialized) <= MAX_OUTPUT_CHARS:
            return result
        result.truncated = True
        if result.ok:
            for _ in range(100):
                result.output = ToolRegistry._shrink(result.output)
                serialized = result.to_content()
                if len(serialized) <= MAX_OUTPUT_CHARS:
                    return result
            result.output = "[output truncated]"
        else:
            result.error = result.error[: MAX_OUTPUT_CHARS // 2]
        return result
