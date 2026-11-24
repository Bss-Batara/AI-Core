"""AI-Core Local Agent."""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BASE_DIR = Path(__file__).parent.resolve()
RULES_FILE = BASE_DIR / "CORE_RULES.md"
MEMORY_FILE = BASE_DIR / "PROJECT_MEMORY.md"
BACKUP_DIR = BASE_DIR / "_backups"
LOG_DIR = BASE_DIR / ".ai-core"
LOG_FILE = LOG_DIR / "agent.log"


@dataclass(frozen=True)
class Config:
    root: Path = BASE_DIR
    ollama_url: str = os.getenv("AI_CORE_OLLAMA_URL", "http://localhost:11434/api/chat")
    model: str = os.getenv("AI_CORE_MODEL", "qwen2.5-coder:3b")
    max_actions: int = int(os.getenv("AI_CORE_MAX_ACTIONS", "8"))
    timeout: int = int(os.getenv("AI_CORE_TIMEOUT", "240"))
    command_timeout: int = int(os.getenv("AI_CORE_COMMAND_TIMEOUT", "60"))


CONFIG = Config()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as stream:
        stream.write(f"[{now()}] {message}\n")


class Project:
    ignored = {".git", ".venv", "__pycache__", "node_modules", "_backups", ".ai-core"}

    def __init__(self, root: Path):
        self.root = root.resolve()

    def safe_path(self, value: str | Path) -> Path:
        candidate = Path(value)
        target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("Access outside project root is prohibited.")
        return target

    def list_files(self, max_depth: int = 5) -> list[str]:
        result: list[str] = []
        for path in self.root.rglob("*"):
            if any(part in self.ignored for part in path.parts):
                continue
            if path.is_file() and len(path.relative_to(self.root).parts) <= max_depth:
                result.append(path.relative_to(self.root).as_posix())
        return sorted(result)

    def read(self, value: str) -> str:
        path = self.safe_path(value)
        if not path.is_file():
            raise FileNotFoundError(value)
        return path.read_text(encoding="utf-8")

    def backup(self, path: Path) -> Path | None:
        if not path.exists():
            return None
        backup_dir = self.root / "_backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = backup_dir / f"{path.name}_{stamp}.bak"
        shutil.copy2(path, backup)
        return backup

    def write(self, value: str, content: str) -> tuple[str, Path | None]:
        path = self.safe_path(value)
        backup = self.backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if path.read_text(encoding="utf-8") != content:
            if backup:
                shutil.copy2(backup, path)
            raise IOError("Write verification failed; previous content restored.")
        return f"Written: {path.relative_to(self.root).as_posix()}", backup

    def context(self) -> str:
        rules_file = self.root / "CORE_RULES.md"
        memory_file = self.root / "PROJECT_MEMORY.md"
        rules = rules_file.read_text(encoding="utf-8") if rules_file.exists() else ""
        memory = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""
        files = "\n".join(self.list_files())
        return f"PROJECT ROOT: {self.root}\nFILES:\n{files}\n\nRULES:\n{rules}\n\nMEMORY:\n{memory}"


class Memory:
    def __init__(self, project: Project):
        self.project = project

    def remember(self, note: str) -> str:
        existing = MEMORY_FILE.read_text(encoding="utf-8") if MEMORY_FILE.exists() else "# AI CORE — PROJECT MEMORY\n"
        MEMORY_FILE.write_text(existing.rstrip() + f"\n\n## EVENT {now()}\n{note.strip()}\n", encoding="utf-8")
        return "Memory updated."


class ControlledTerminal:
    allowed = {"python", "python3", "git", "pytest", "gh", "npm", "node"}
    blocked = {"del", "erase", "format", "rmdir", "rd", "shutdown", "reg", "diskpart"}

    def __init__(self, project: Project, approve: Callable[[str], bool]):
        self.project = project
        self.approve = approve

    def run(self, command: str, timeout: int = 60, approval: bool = True) -> str:
        if any(token in command for token in ("|", ">", "<", "&", ";", "`", "$(", "\n")):
            raise ValueError("Shell operators are prohibited.")
        parts = shlex.split(command, posix=(os.name != "nt"))
        if not parts or parts[0].lower() in self.blocked or parts[0].lower() not in self.allowed:
            raise ValueError(f"Command is not allowlisted: {command}")
        if approval and not self.approve(command):
            return "Command cancelled by user."
        result = subprocess.run(parts, cwd=self.project.root, capture_output=True, text=True, timeout=timeout)
        return f"exit_code={result.returncode}\n{(result.stdout + result.stderr).strip()}".strip()


class GitManager:
    def __init__(self, terminal: ControlledTerminal):
        self.terminal = terminal

    def run(self, operation: str) -> str:
        commands = {"status": "git status --short", "diff": "git diff --stat", "log": "git log -5 --oneline", "branch": "git branch --show-current"}
        if operation not in commands:
            raise ValueError("Git operation must be status, diff, log, or branch.")
        return self.terminal.run(commands[operation], approval=False)


class Ollama:
    def __init__(self, config: Config):
        self.config = config

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({"model": self.config.model, "stream": False, "messages": messages, "options": {"temperature": 0.1}}).encode()
        request = urllib.request.Request(self.config.ollama_url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ConnectionError(f"Ollama unavailable at {self.config.ollama_url}: {exc}") from exc
        content = data.get("message", {}).get("content", "")
        if not content.strip():
            raise ValueError("Ollama returned an empty response.")
        return content


def extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Model response did not contain valid JSON.")
        data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict) or not isinstance(data.get("action"), str):
        raise ValueError("Action JSON must contain a string action.")
    return data


def validate_python(path: Path) -> str:
    if path.suffix.lower() != ".py":
        return "syntax_check=skipped"
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return "syntax_check=passed"


AGENT_INSTRUCTIONS = """You are AI-Core, a local autonomous coding agent.
Return ONLY one valid JSON object, without markdown.
Actions:
{"action":"plan","steps":["..."],"response":"..."}
{"action":"list_files"}
{"action":"read_file","path":"relative/path"}
{"action":"write_file","path":"relative/path","content":"complete file content"}
{"action":"run_command","command":"python -m pytest"}
{"action":"git","operation":"status|diff|log|branch"}
{"action":"github","command":"gh auth status"}
{"action":"remember","note":"durable project decision"}
{"action":"answer","response":"final answer"}
Rules: inspect files before editing; never use paths outside project root; never delete files; write complete content; preserve behavior; use plan before multi-file work; after writing, verify and then answer."""


class Agent:
    def __init__(self, project: Project, config: Config = CONFIG, interactive: bool = True):
        self.project = project
        self.config = config
        self.interactive = interactive
        self.memory = Memory(project)
        self.ollama = Ollama(config)
        self.read_files: set[Path] = set()
        self.terminal = ControlledTerminal(project, self._approve)
        self.git = GitManager(self.terminal)

    def _approve(self, description: str) -> bool:
        if not self.interactive:
            return False
        return input(f"Approve {description}? (y/n): ").strip().lower() == "y"

    def _messages(self, prompt: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.project.context() + "\n\n" + AGENT_INSTRUCTIONS}, {"role": "user", "content": prompt}]

    def _diff(self, old: str, new: str, path: str) -> str:
        return "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile=f"Original: {path}", tofile=f"Modified: {path}", lineterm=""))

    def execute(self, prompt: str) -> str:
        messages = self._messages(prompt)
        for cycle in range(self.config.max_actions):
            log(f"cycle={cycle + 1} prompt={prompt[:120]}")
            try:
                action_data = extract_json(self.ollama.chat(messages))
            except Exception as exc:
                return f"AI-Core decision error: {exc}"
            action = action_data["action"]
            if action == "answer":
                return str(action_data.get("response", "Task completed."))
            if action == "plan":
                print("\nPlan:")
                for index, step in enumerate(action_data.get("steps", []), 1):
                    print(f"{index}. {step}")
                messages.extend([{"role": "assistant", "content": json.dumps(action_data)}, {"role": "user", "content": "Plan accepted. Continue with the first required action."}])
                continue
            try:
                result = self._dispatch(action_data)
            except Exception as exc:
                result = f"Tool error: {exc}"
            messages.extend([{"role": "assistant", "content": json.dumps(action_data)}, {"role": "user", "content": f"TOOL RESULT:\n{result}\nContinue the task and return JSON only."}])
        return "AI-Core stopped: maximum action cycles reached."

    def _dispatch(self, data: dict[str, Any]) -> str:
        action = data["action"]
        if action == "list_files":
            return "\n".join(self.project.list_files())
        if action == "read_file":
            path = self.project.safe_path(str(data.get("path", "")))
            result = self.project.read(str(path))
            self.read_files.add(path)
            return result
        if action == "write_file":
            relative = str(data.get("path", ""))
            path = self.project.safe_path(relative)
            content = data.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty file content rejected.")
            if path.exists() and path not in self.read_files:
                raise PermissionError("Existing file must be read before modification.")
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            print(self._diff(old, content, relative) or "No changes detected.")
            if old == content:
                return "No changes detected; generate an actual modification."
            if not self._approve(f"write {relative}"):
                return "Write cancelled by user."
            result, backup = self.project.write(relative, content)
            verification = validate_python(path)
            self.read_files.add(path)
            return f"{result}; {verification}; backup={backup}"
        if action == "run_command":
            return self.terminal.run(str(data.get("command", "")), self.config.command_timeout)
        if action == "git":
            return self.git.run(str(data.get("operation", "status")))
        if action == "github":
            command = str(data.get("command", "gh auth status"))
            if not command.strip().lower().startswith("gh "):
                raise ValueError("GitHub commands must start with gh.")
            return self.terminal.run(command, self.config.command_timeout)
        if action == "remember":
            return self.memory.remember(str(data.get("note", "")))
        raise ValueError(f"Unknown action: {action}")


def direct_command(agent: Agent, value: str) -> bool:
    if value == "/files":
        print("\n".join(agent.project.list_files()))
        return True
    if value.startswith("/read "):
        try:
            print(agent.project.read(value[6:].strip()))
        except Exception as exc:
            print(f"Error: {exc}")
        return True
    if value == "/status":
        try:
            print(agent.git.run("status"))
        except Exception as exc:
            print(f"Error: {exc}")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-Core local coding agent")
    parser.add_argument("prompt", nargs="*", help="one-shot task; omit for interactive mode")
    parser.add_argument("--root", default=str(BASE_DIR), help="project root")
    parser.add_argument("--model", default=CONFIG.model)
    args = parser.parse_args()
    config = Config(root=Path(args.root).resolve(), model=args.model)
    project = Project(config.root)
    agent = Agent(project, config)
    print(f"AI-Core | root={project.root} | model={config.model}")
    print("Commands: /files, /read <path>, /status, exit")
    if args.prompt:
        prompt = " ".join(args.prompt)
        if not direct_command(agent, prompt):
            print(agent.execute(prompt))
        return 0
    while True:
        try:
            prompt = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAI-Core stopped.")
            return 0
        if prompt.lower() in {"exit", "quit"}:
            return 0
        if not prompt:
            continue
        if not direct_command(agent, prompt):
            print(f"\nAI: {agent.execute(prompt)}")


if __name__ == "__main__":
    raise SystemExit(main())
