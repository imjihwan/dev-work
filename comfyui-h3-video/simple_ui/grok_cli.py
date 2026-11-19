"""Text-only adapter for the pinned official Grok CLI; never reads media or auth tokens."""
import json
import math
import os
import queue
from pathlib import Path
import subprocess
import tempfile
import time
import threading
from datetime import datetime, timezone

CLI_VERSION = "1.0.89"
EFFORTS = ("low", "medium", "high", "xhigh")
TIMEOUT_SECONDS = {"low": 180, "medium": 300, "high": 600, "xhigh": 900}
MAX_EVENT_BYTES = 1_000_000
MAX_STREAM_BYTES = 8_000_000
SCHEMA_OUTPUT_TOOL = "StructuredOutput"
OUTPUT_TRANSPORT = """Return one final object matching the requested JSON schema. If the CLI asks
for its internal StructuredOutput formatter, use it to deliver that final object.
It is an output envelope, not an app action. Encode any proposed app operations
inside the requested JSON; do not invoke them as CLI tools."""
FAILURE_MESSAGES={
    "read_error":"Grok CLI 응답을 읽는 중 연결 오류가 발생했습니다.",
    "stream_size_limit":"Grok 응답이 수신 크기 제한을 넘었습니다.",
    "invalid_init":"Grok CLI의 로그인·도구 실행 환경을 확인하지 못했습니다.",
    "init_auth_source":"Grok CLI가 구독 OAuth 인증으로 시작되지 않았습니다.",
    "init_tools_present":"Grok CLI가 앱 전용 연결에 허용되지 않은 도구를 활성화했습니다.",
    "init_skills_present":"Grok CLI가 앱 전용 연결에 허용되지 않은 스킬을 활성화했습니다.",
    "init_mcp_present":"Grok CLI가 앱 전용 연결에 허용되지 않은 MCP 연결을 활성화했습니다.",
    "init_changed":"Grok CLI가 응답 도중 다른 실행 환경으로 전환됐습니다.",
    "init_after_result":"Grok CLI가 최종 응답 뒤에 시작 알림을 반환했습니다.",
    "provider_error_event":"Grok CLI가 오류 응답을 반환했습니다.",
    "unexpected_user_event":"Grok CLI 응답에 예상하지 않은 중간 대화 이벤트가 포함됐습니다.",
    "tool_event":"Grok이 JSON 변경안 대신 도구 호출 형식으로 응답했습니다.",
    "assistant_tool_event":"Grok이 JSON 변경안 대신 도구 호출 형식으로 응답했습니다.",
    "missing_web_search":"외부 검색 결과를 확인하지 못했습니다. 검색 없이 찾았다고 답하지 않았습니다.",
    "json_delta_event":"Grok이 JSON 변경안 대신 도구 인수 스트림으로 응답했습니다.",
    "stream_sequence":"Grok CLI 스트림의 응답 순서를 확인하지 못했습니다.",
    "assistant_sequence":"Grok CLI 스트림의 응답 순서를 확인하지 못했습니다.",
    "duplicate_result":"Grok CLI가 최종 응답을 중복 반환했습니다.",
    "missing_terminal":"Grok CLI가 최종 완료 응답을 반환하지 않았습니다.",
    "nonterminal_stop":"Grok 응답이 정상 완료되기 전에 끝났습니다.",
    "missing_structured_output":"Grok 응답에 적용 가능한 JSON 변경안이 없습니다.",
    "event_not_object":"Grok CLI의 응답 JSON 형식이 올바르지 않습니다.",
    "malformed_event":"Grok CLI 응답을 JSON으로 해석하지 못했습니다.",
}


def clean_progress(info):
    """Only operational metadata can leave the CLI, never thinking or partial JSON."""
    if not isinstance(info, dict): return {}
    result = {}
    if info.get("cli_stage") in ("starting", "waiting", "thinking", "answer", "check"):
        result["cli_stage"] = info["cli_stage"]
    for key in ("cli_elapsed_s", "cli_limit_s", "cli_signals", "cli_idle_s"):
        value = info.get(key)
        if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10_000_000:
            result[key] = value
    return result
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
Return only the requested structured answer. The CLI StructuredOutput formatter
is an output envelope. No app/file tools, repository context or attachments.
"""


class GrokCLI:
    def __init__(self, home):
        self.home = Path(home)
        self.exe = self.home / "grok-cli" / "bin" / "grok.exe"
        self.account = self.home / "grok-account"
        self.metrics_lock = threading.Lock()

    def _record_metrics(self, metrics):
        """A small numeric-only history. Never persist prompts or raw provider events."""
        allowed = {"at", "model", "effort", "elapsed_s", "limit_s", "request_bytes", "outcome", "exit_code",
                   "reported_api_ms", "cli_ms", "turns", "input_tokens", "output_tokens", "failure_reason",
                   "init_events", "init_tools_count", "init_skills_count", "init_mcp_count", "init_empty_fields_omitted", "schema_output_calls", "web_search_calls", "web_search_results"}
        record = {key: value for key, value in metrics.items() if key in allowed}
        if record.get("failure_reason") not in FAILURE_MESSAGES:record.pop("failure_reason",None)
        if not self.home.is_dir(): return
        try:
            with self.metrics_lock:
                path = self.home / "grok-timings.jsonl"
                if path.exists() and path.stat().st_size > 128 * 1024:
                    os.replace(path, self.home / "grok-timings.previous.jsonl")
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
        except OSError:
            pass  # Diagnostic disk errors must never cause a valid reply to fail.

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

    def command(self, work, system, schema, effort="high", web_search=False):
        if effort not in EFFORTS:
            raise ValueError("도우미 응답 방식을 확인해 주세요.")
        return [str(self.exe), "--model", "grok-4.7", "--reasoning-effort", effort, "--cwd", str(work), "--agent", str(work / "agent.md"),
                "--system-prompt-override", system+"\n\n"+OUTPUT_TRANSPORT, "--prompt-file", str(work / "prompt.txt"),
                "--verbatim", "--output-format", "streaming-messages-json", "--include-partial-messages", "--json-schema", json.dumps(schema),
                "--disallowed-tools", "todo_write", "--permission-mode", "dontAsk", "--deny", "*", "--no-subagents",
                *([] if web_search else ["--disable-web-search"]), "--no-plan", "--max-turns", "6" if web_search else "1"]

    def complete(self, system, content, schema, cancel_event, effort="high", on_progress=None, timeout_s=None, web_search=False):
        if type(web_search) is not bool:raise ValueError("외부 검색 설정을 확인해 주세요.")
        if effort not in TIMEOUT_SECONDS:
            raise ValueError("도우미 응답 방식을 확인해 주세요.")
        if timeout_s is not None and (type(timeout_s) not in (int,float) or not math.isfinite(timeout_s) or timeout_s<=0):
            raise ValueError("도우미 대기 시간을 확인해 주세요.")
        if not self.ready():
            raise ValueError("Grok CLI 로그인이 필요합니다. PC에서 Connect-Grok.ps1을 실행해 주세요.")
        # A new empty working directory and curated profile prevent project/user
        # instruction discovery. Prompts are not exposed in process command lines.
        with tempfile.TemporaryDirectory(prefix="h3-grok-") as directory:
            work = Path(directory)
            (work / "agent.md").write_text(PROFILE, encoding="utf-8")
            payload = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            (work / "prompt.txt").write_text(payload, encoding="utf-8")
            started = time.monotonic()
            limit = TIMEOUT_SECONDS[effort]
            if timeout_s is not None: limit = min(limit,max(1,math.ceil(timeout_s)))
            metrics = {"at": datetime.now(timezone.utc).isoformat(), "model": "grok-4.7", "effort": effort,
                       "limit_s": limit, "request_bytes": len(payload.encode("utf-8")), "outcome": "invalid_response"}
            process = subprocess.Popen(self.command(work, system, schema, effort,web_search=web_search), cwd=work,
                env=self.environment(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = started + limit
            next_progress = started
            # Drain stdout while the child is running. Keep only init/result; raw
            # reasoning and partial JSON are discarded after classifying the event.
            inbox = queue.Queue(maxsize=16)
            stopped = threading.Event()
            def enqueue(item):
                while not stopped.is_set():
                    try: inbox.put(item, timeout=.1); return
                    except queue.Full: pass
            def read_output():
                try:
                    while not stopped.is_set():
                        line = process.stdout.readline(MAX_EVENT_BYTES + 1)
                        if not line: break
                        enqueue(("line", line))
                        if len(line) > MAX_EVENT_BYTES: break
                except (OSError, ValueError): enqueue(("error", None))
                finally: enqueue(("eof", None))
            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            initial, results = [], []
            # This is the CLI's schema formatter, intercepted by the CLI before
            # tool execution. Keep only opaque call IDs/block indices, never args.
            schema_calls, schema_blocks, web_calls, web_search_calls, web_results = set(), {}, set(), set(), set()
            def schema_tool(block):
                if block.get("type")!="tool_use" or block.get("name")!=SCHEMA_OUTPUT_TOOL:return False
                identity=block.get("id")
                if not isinstance(identity,str) or not 1<=len(identity)<=256:return False
                schema_calls.add(identity)
                metrics["schema_output_calls"]=len(schema_calls)
                return True
            def web_tool(block):
                if not web_search:return False
                search=block.get("type")=="server_tool_use" and block.get("name")=="web_search"
                # Grok's hosted open-page/read actions use this generic client
                # frame; they do not activate a local filesystem or shell tool.
                read=block.get("type")=="tool_use" and block.get("name")=="Web search:"
                if not (search or read):return False
                identity=block.get("id")
                if not isinstance(identity,str) or not 1<=len(identity)<=256:return False
                web_calls.add(identity)
                if search:web_search_calls.add(identity)
                metrics["web_search_calls"]=len(web_search_calls)
                return True
            def web_result(block):
                if not web_search or block.get("type")!="web_search_tool_result":return
                identity=block.get("tool_use_id");hits=block.get("content")
                if identity in web_calls and isinstance(hits,list) and any(isinstance(hit,dict) and isinstance(hit.get("url"),str) and hit["url"].startswith(("https://","http://")) for hit in hits):
                    web_results.add(identity);metrics["web_search_results"]=len(web_results)
            def schema_tool_result(event):
                message=event.get("message")
                if not isinstance(message,dict):return False
                blocks=message.get("content")
                return isinstance(blocks,list) and bool(blocks) and all(isinstance(block,dict)
                    and block.get("type")=="tool_result" and block.get("tool_use_id") in (schema_calls|web_calls) for block in blocks)
            size, signals = 0, 0
            stage, last_signal, eof = "starting", None, False
            def invalid(reason="malformed_event"):
                reason=metrics.setdefault("failure_reason",reason)
                raise ValueError(FAILURE_MESSAGES.get(reason,FAILURE_MESSAGES["malformed_event"])+" 원문은 유지했습니다.")
            try:
                while True:
                    if cancel_event.is_set():
                        metrics["outcome"] = "cancelled"
                        raise RuntimeError("Grok 작성을 취소했습니다. 이미 처리된 요청은 계정 사용량에 포함될 수 있습니다.")
                    now = time.monotonic()
                    if now >= deadline:
                        metrics["outcome"] = "timeout"
                        raise RuntimeError(f"Grok 응답 시간이 초과됐습니다({limit}초). Grok 응답을 기다리다가 이 호출만 종료했습니다. 자동 재전송하지 않았습니다.")
                    if on_progress is not None and now >= next_progress:
                        info = {"cli_elapsed_s": round(now-started,1), "cli_limit_s": limit,
                                "cli_stage": stage, "cli_signals": signals}
                        if last_signal is not None: info["cli_idle_s"] = round(now-last_signal,1)
                        try: on_progress(info)
                        except Exception: pass
                        next_progress = now + 1
                    if eof:
                        try: process.wait(timeout=.2); break
                        except subprocess.TimeoutExpired: continue
                    try: kind, raw = inbox.get(timeout=.2)
                    except queue.Empty: continue
                    if kind == "eof": eof = True; continue
                    if kind == "error": invalid("read_error")
                    size += len(raw)
                    if len(raw) > MAX_EVENT_BYTES or size > MAX_STREAM_BYTES: invalid("stream_size_limit")
                    if not raw.strip(): continue
                    try:
                        previous_stage = stage
                        event = json.loads(raw)
                        if not isinstance(event, dict): invalid("event_not_object")
                        event_type = event.get("type")
                        if event_type == "system" and event.get("subtype") == "init":
                            if results:invalid("init_after_result")
                            metrics["init_events"]=metrics.get("init_events",0)+1
                            metrics["init_empty_fields_omitted"]=sum(event.get(key) is None for key in ("tools","skills","mcp_servers"))
                            for key,field,reason in (("tools","init_tools_count","init_tools_present"),("skills","init_skills_count","init_skills_present"),("mcp_servers","init_mcp_count","init_mcp_present")):
                                value=event.get(key)
                                metrics[field]=len(value) if isinstance(value,(list,dict)) else 0 if value is None else -1
                                if key=="tools" and isinstance(value,list) and value and all(tool in ([SCHEMA_OUTPUT_TOOL,"web_search"] if web_search else [SCHEMA_OUTPUT_TOOL]) for tool in value):continue
                                if value not in (None,[],{}):invalid(reason)
                            if event.get("apiKeySource")!="oauth":invalid("init_auth_source")
                            # Empty/missing collections express the same no-tools
                            # environment. Repeated identical init notices are inert.
                            normalized={"tools":[],"skills":[],"mcp_servers":[],"apiKeySource":"oauth","model":event.get("model")}
                            if initial:
                                old_model=initial[0].get("model");new_model=normalized.get("model")
                                if old_model is not None and new_model is not None and old_model!=new_model:invalid("init_changed")
                                if old_model is None:initial[0]["model"]=new_model
                            else:
                                initial.append(normalized);stage="waiting"
                        elif event_type == "result":
                            results.append(event)
                            if len(results) != 1: invalid("duplicate_result")
                            stage = "check"
                        elif event_type == "error": invalid("provider_error_event")
                        elif event_type == "user":
                            if not initial or results or not schema_tool_result(event):invalid("unexpected_user_event")
                        elif event_type == "stream_event":
                            if not initial or results: invalid("stream_sequence")
                            frame = event.get("event", {})
                            frame_type = frame.get("type")
                            block = frame.get("content_block", {}) if frame_type == "content_block_start" else frame.get("delta", {})
                            block_type = block.get("type")
                            if frame_type in ("message_start","message_stop"):schema_blocks.clear()
                            if frame_type == "content_block_start":
                                web_result(block)
                                index=frame.get("index")
                                if block_type in ("tool_use","server_tool_use"):
                                    if type(index) is not int or index<0 or not (schema_tool(block) or web_tool(block)):invalid("tool_event")
                                    schema_blocks[index]=block["id"];stage="answer"
                                else:schema_blocks.pop(index,None)
                            if block_type == "input_json_delta":
                                if frame.get("index") not in schema_blocks:invalid("json_delta_event")
                                stage="answer";signals+=1;last_signal=now
                            if frame_type == "content_block_stop":schema_blocks.pop(frame.get("index"),None)
                            next_stage = "thinking" if block_type in ("thinking", "thinking_delta", "redacted_thinking") else "answer" if block_type in ("text", "text_delta") else None
                            if next_stage:
                                stage = next_stage
                                if frame_type == "content_block_delta": signals += 1; last_signal = now
                        elif event_type == "assistant":
                            if not initial or results: invalid("assistant_sequence")
                            blocks = event.get("message", {}).get("content", [])
                            for block in blocks:
                                web_result(block)
                                if block.get("type") in ("tool_use","server_tool_use") and not (schema_tool(block) or web_tool(block)):invalid("assistant_tool_event")
                        # No raw event or raw block survives this iteration.
                        del event, raw
                    except (ValueError, TypeError, AttributeError): invalid("malformed_event")
                    if stage != previous_stage or signals == 1 and last_signal == now:
                        next_progress = 0
                if cancel_event.is_set():
                    metrics["outcome"] = "cancelled"
                    raise RuntimeError("Grok 작성을 취소했습니다.")
                if process.returncode:
                    metrics["outcome"] = "provider_error" if process.returncode else "invalid_response"
                    raise ValueError("Grok CLI 요청이 실패했습니다. 로그인·구독 사용 한도를 확인해 주세요. API로 자동 전환하지 않았습니다.")
                try:
                    if len(initial) != 1 or len(results) != 1:
                        invalid("missing_terminal")
                    if initial[0].get("tools") != [] or initial[0].get("skills") != [] or initial[0].get("mcp_servers") != [] or initial[0].get("apiKeySource") != "oauth":
                        raise ValueError
                    response = results[0]
                    for source, target in (("duration_api_ms", "reported_api_ms"), ("duration_ms", "cli_ms"), ("num_turns", "turns")):
                        if type(response.get(source)) in (int, float): metrics[target] = response[source]
                    for key in ("input_tokens", "output_tokens"):
                        usage = response.get("usage")
                        value = usage.get(key) if isinstance(usage, dict) else None
                        if type(value) in (int, float): metrics[key] = value
                    if response.get("stop_reason") != "end_turn" or response.get("is_error"):
                        invalid("nonterminal_stop")
                    if web_search and not web_results:invalid("missing_web_search")
                    draft = response.get("structured_output")
                    if not isinstance(draft, dict):
                        invalid("missing_structured_output")
                except (ValueError, TypeError, AttributeError):
                    # Do not echo CLI errors, reasoning or response text into logs/status.
                    invalid("missing_terminal")
                metrics["outcome"] = "ok"
                return draft
            finally:
                stopped.set()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                reader.join(timeout=1)
                if process.stdout:
                    process.stdout.close()
                metrics.update(elapsed_s=round(time.monotonic()-started,1),exit_code=process.returncode)
                self._record_metrics(metrics)
