"""Text-only adapter for the pinned official Grok CLI; never reads media or auth tokens."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

CLI_VERSION = "1.0.89"
PROFILE = """---
name: h3-text-only
description: Text-only video prompt editor without local tools or file context
promptMode: full
permissionMode: dontAsk
toolConfig:
  tools:
    - id: GrokBuild:todo_write
injectDefaultTools: false
disallowedTools: [todo_write]
agentsMd: false
discoverSkills: false
inheritSkills: false
skills: []
mcpServers: []
hooks: {}
---
Return only the requested JSON. No tools, file access, repository context or attachments.
"""


class GrokCLI:
    def __init__(self, home):
        self.home = Path(home)
        self.exe = self.home / "grok-cli" / "bin" / "grok.exe"
        self.account = self.home / "grok-account"

    def ready(self):
        # Presence only. Let the CLI own tokens and refresh; do not deserialize credentials.
        return self.exe.is_file() and (self.account / "auth.json").is_file()

    def environment(self):
        # Prevent inherited API keys, provider overrides, plugins and custom hooks from
        # changing a subscription request into a billed API request or loading user tools.
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(("GROK_", "XAI_", "ANTHROPIC_", "OPENAI_"))
               and key.upper() not in ("RUST_LOG", "RUST_BACKTRACE", "CLAUDE_CONFIG_DIR")}
        env.update(GROK_HOME=str(self.account), GROK_DISABLE_AUTOUPDATER="1",
                   GROK_MEMORY="0", GROK_SUBAGENTS="0", GROK_GOAL="0",
                   GROK_WEB_FETCH="0", GROK_WRITE_FILE="0", GROK_LSP_TOOLS="0",
                   GROK_PROMPT_SUGGESTIONS="0")
        return env

    def command(self, work, system, schema):
        return [str(self.exe), "--model", "grok-4.7", "--cwd", str(work), "--agent", str(work / "agent.md"),
                "--system-prompt-override", system, "--prompt-file", str(work / "prompt.txt"),
                "--verbatim", "--output-format", "streaming-messages-json", "--json-schema", json.dumps(schema),
                "--disallowed-tools", "todo_write", "--permission-mode", "dontAsk", "--deny", "*", "--no-subagents",
                "--disable-web-search", "--no-plan", "--max-turns", "1"]

    def complete(self, system, content, schema, cancel_event):
        if not self.ready():
            raise ValueError("Grok CLI 로그인이 필요합니다. PC에서 Connect-Grok.ps1을 실행해 주세요.")
        # A new empty working directory and curated profile prevent project/user
        # instruction discovery. Prompts are not exposed in process command lines.
        with tempfile.TemporaryDirectory(prefix="h3-grok-") as directory:
            work = Path(directory)
            (work / "agent.md").write_text(PROFILE, encoding="utf-8")
            (work / "prompt.txt").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
            process = subprocess.Popen(self.command(work, system, schema), cwd=work,
                env=self.environment(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 180
            try:
                while True:
                    if cancel_event.is_set():
                        raise RuntimeError("Grok 작성을 취소했습니다. 이미 처리된 요청은 계정 사용량에 포함될 수 있습니다.")
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Grok 응답 시간이 초과됐습니다. 로그인·계정 사용 한도를 확인해 주세요.")
                    try:
                        raw, _ = process.communicate(timeout=.2)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if cancel_event.is_set():
                    raise RuntimeError("Grok 작성을 취소했습니다.")
                if process.returncode or len(raw) > 1_000_000:
                    raise ValueError("Grok CLI 요청이 실패했습니다. 로그인·구독 사용 한도를 확인해 주세요. API로 자동 전환하지 않았습니다.")
                try:
                    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
                    initial = [event for event in events if event.get("type") == "system" and event.get("subtype") == "init"]
                    results = [event for event in events if event.get("type") == "result"]
                    if len(initial) != 1 or len(results) != 1:
                        raise ValueError
                    if initial[0].get("tools") != [] or initial[0].get("skills") != [] or initial[0].get("mcp_servers") != [] or initial[0].get("apiKeySource") != "oauth":
                        raise ValueError
                    response = results[0]
                    if response.get("stop_reason") != "end_turn" or response.get("is_error"):
                        raise ValueError
                    if any(event.get("type") in ("error", "user") for event in events):
                        raise ValueError
                    draft = response.get("structured_output")
                    if not isinstance(draft, dict):
                        raise ValueError
                except (ValueError, TypeError, AttributeError):
                    # Do not echo CLI errors, reasoning or response text into logs/status.
                    raise ValueError("Grok의 JSON 응답을 확인하지 못했습니다. 원문은 유지했습니다.") from None
                return draft
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                if process.stdout:
                    process.stdout.close()
