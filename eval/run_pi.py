#!/usr/bin/env python3
"""Finite, isolated pi runs. Execution evidence is deliberately not a quality score."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = ["request_fulfillment", "factual_grounding", "professional_depth",
              "content_richness", "image_relevance", "layout_legibility",
              "delivery_integrity", "teaching_or_actionability"]
PRINT_LOCK = threading.Lock()
STOP = threading.Event()
SKIP = {".git", ".pi", "__pycache__", ".DS_Store", ".pytest_cache", ".env"}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def progress(message):
    with PRINT_LOCK:
        print(message, file=sys.stderr, flush=True)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def inventory(root):
    """Hash content, including local prepared fonts/dependencies, without following links."""
    result = {}
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root)
        if any(p in SKIP or p.startswith(".env.") for p in rel.parts):
            continue
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(Path(root).resolve()):
                raise ValueError(f"Snapshot contains an external symlink: {rel}")
            result[str(rel)] = {"symlink": os.readlink(path)}
        elif path.is_file():
            result[str(rel)] = {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
    return result


def copy_tree(source, target):
    # APFS copy-on-write avoids multiplying the prepared font/dependency footprint.
    # Each case still owns independent inodes; Linux uses ordinary independent copies.
    if sys.platform == "darwin":
        proc = subprocess.run(["/bin/cp", "-cR", str(source), str(target)], capture_output=True)
        if proc.returncode == 0:
            return
        if Path(target).exists():
            shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)


def git_identity(repo):
    def git(*args):
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
        return proc.stdout if proc.returncode == 0 else b""
    return {"commit": git("rev-parse", "HEAD").decode().strip() or None,
            "branch": git("branch", "--show-current").decode().strip() or None,
            "trackedDiffSha256": digest(git("diff", "HEAD", "--", "skills/open-pptd")),
            "note": "Snapshot inventory also covers untracked skill files and prepared runtime files."}


def make_snapshot(source, target):
    before = inventory(source)
    shutil.copytree(source, target, symlinks=True,
                    ignore=lambda _d, names: [n for n in names if n in SKIP or n.startswith(".env.")])
    copied = inventory(target)
    if copied != before or inventory(source) != before:
        raise RuntimeError("Skill changed while snapshotting; retry after edits settle.")
    return {"treeSha256": digest(json.dumps(copied, sort_keys=True).encode()), "files": copied}


def minimal_env():
    allowed = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR",
               "SHELL", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "CHROME_PATH",
               "CHROMIUM_PATH", "PUPPETEER_EXECUTABLE_PATH", "SSL_CERT_FILE", "SSL_CERT_DIR",
               "REQUESTS_CA_BUNDLE", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY"}
    return {k: v for k, v in os.environ.items() if k in allowed}


def prepare_config(source, destination, provider, model, key_env=None, thinking=None):
    """Copy only the selected provider; never serialize unrelated credentials/settings."""
    source, destination = Path(source), Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    read = lambda name: json.loads((source / name).read_text()) if (source / name).exists() else {}
    settings = read("settings.json")
    provider = provider or settings.get("defaultProvider")
    model = model or settings.get("defaultModel")
    if not provider or not model:
        raise ValueError("Specify --provider and --model, or configure pi defaults.")
    env, secrets = minimal_env(), []
    selected = read("models.json").get("providers", {}).get(provider)
    auth = read("auth.json").get(provider)
    if key_env:
        if not os.environ.get(key_env):
            raise ValueError("The selected --key-env is unset or empty.")
        auth = {"type": "api_key", "key": os.environ[key_env]}
        secrets.append(os.environ[key_env])

    def resolve_credential(value):
        if not isinstance(value, str):
            return value
        if value.startswith("!"):
            raise ValueError("Credential commands are not run by the benchmark; use --key-env.")
        # Old pi configs may use a bare env variable name. Normalize only this private copy.
        if value in os.environ:
            value = os.environ[value]
        else:
            def replace(match):
                name = match.group(1) or match.group(2)
                if name not in os.environ:
                    raise ValueError("A selected provider credential environment variable is unset.")
                return os.environ[name]
            value = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", replace, value)
        if value:
            secrets.append(value)
        name = f"PI_EVAL_CREDENTIAL_{len(secrets)}"
        env[name] = value
        return "$" + name

    if selected is not None:
        selected = json.loads(json.dumps(selected))
        selected["models"] = [m for m in selected.get("models", []) if m.get("id") == model]
        for item in [selected, *selected.get("models", [])]:
            if "apiKey" in item:
                if key_env:
                    item["apiKey"] = os.environ[key_env]
                item["apiKey"] = resolve_credential(item["apiKey"])
            if "headers" in item:
                item["headers"] = {k: resolve_credential(v) for k, v in item["headers"].items()}
        write_json(destination / "models.json", {"providers": {provider: selected}})
    if auth:
        write_json(destination / "auth.json", {provider: auth})
        secrets.extend(str(v) for k, v in auth.items() if k in ("key", "access", "refresh") and v)
    elif selected is None:
        standard = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                    "moonshotai": "MOONSHOT_API_KEY", "google": "GEMINI_API_KEY"}.get(provider)
        if standard and os.environ.get(standard):
            env[standard] = os.environ[standard]
            secrets.append(os.environ[standard])
    write_json(destination / "settings.json", {"defaultProvider": provider, "defaultModel": model,
               "defaultThinkingLevel": thinking or settings.get("defaultThinkingLevel", "off"),
               "quietStartup": True, "packages": [], "skills": [], "extensions": []})
    for path in destination.iterdir():
        path.chmod(0o600)
    env.update(PI_CODING_AGENT_DIR=str(destination), PI_TELEMETRY="0", PI_OFFLINE="1")
    return env, sorted(set(secrets), key=len, reverse=True), provider, model


def redact(text, secrets):
    for secret in secrets:
        if len(secret) >= 6:
            text = text.replace(secret, "[REDACTED]")
    return re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1[REDACTED]", text)


def build_prompt(case, skill, allow_web, model_inputs=None):
    networking = ("允许检索公开网页和图片；内置 bash 可通过 curl/Python 获取公开来源，配图使用 skill 现有搜图脚本。记录来源位置和访问日期；时事先核实前提。不要上传无关私有资料。"
                  if allow_web else "本次只用本地资料；不得联网检索资料、图片或临时安装依赖。无法核实的时事和数据明确保留待核实。模型 API 调用不属于此素材联网限制。")
    vision = ("本轮模型配置支持图像输入，可用 read 查看本地渲染 PNG，并记录实际查看范围。"
              if model_inputs and "image" in model_inputs else
              "本轮模型未声明图像输入能力。仍须生成 PNG 并运行现有静态/辅助审计；把视觉检查标为待独立看图，不要把 read PNG、像素统计或自写 DOM 检查说成已看图。")
    return f"""使用 open-pptd skill 完成下面的用户请求。先读取 {skill / 'SKILL.md'}，遵循其中当前流程。

用户原始请求（逐字保留）：
{case['prompt']}

本轮执行条件：
- 当前日期 {datetime.now().astimezone().date().isoformat()}。无指定页数时以约10页为起点；常州历史建议12页以便古代史约3页；5分钟汇报以6–8页为宜。明确页数要求优先。
- 这是非交互单次运行。必要素材缺失时写 output/NEEDS_INPUT.md 说明；可以完成明确待填的框架，但不要伪造财务、个人业绩、主持稿或未证实事实。不得声称已读未提供附件。
- {networking}
- 只在当前工作目录创建或修改产物；正式 PPTD/PPTX/HTML 统一保存在 output/deck/，研究网页放 output/research/，格式实验放 output/.pattern-test/。技能目录是本轮独立副本，只读使用；不修改仓库、用户项目、全局配置，不读取密钥、凭据文件或打印环境变量。
- pi 有 read/bash/edit/write 等基本工具，必须实际调用；普通文本里的 <tool_call> 不会执行。不存在的任务/浏览器工具不要猜名字；没有子代理工具就顺序完成。{vision}
- 交付 skill 默认格式（PPTD/PPTX/HTML）并做实际渲染检查；不能完成的步骤如实记录。不得把代码正常退出或文件存在当成质量通过。
- 最后写 output/EVAL_RESULT.json：{{"status":"completed 或 needs_input 或 failed","notes":["简短说明"],"files":["相对路径"]}}。它只是作者自述，不代替独立评测。
"""


def artifacts(root):
    result = []
    if not Path(root).exists():
        return result
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
            continue
        suffix = path.suffix.lower()
        if suffix in {".pptd", ".pptx", ".html", ".page", ".png", ".jpg", ".jpeg", ".pdf"}:
            result.append({"path": str(path.relative_to(root)), "kind": suffix[1:],
                           "bytes": path.stat().st_size if path.is_file() else None})
    return result


def delivery_artifacts(found):
    """Formal output locations, not research HTML or format experiments.

    Root-level decks remain supported for older prompts. This is a file-presence
    check only; validity, page count, freshness and quality require review.
    """
    groups = []
    manifests = [x for x in found if x["kind"] == "pptd" and x.get("bytes")]
    for manifest in found:
        path = Path(manifest["path"])
        if manifest["kind"] != "pptd" or path.parent not in (Path("."), Path("deck")) or not manifest.get("bytes"):
            continue
        expected = {path, path.with_suffix(".pptx"), path.with_suffix(".html")}
        if sum(Path(x["path"]).parent == path.parent for x in manifests) == 1:
            expected.update({path.parent / "index.html", path.parent / "html/index.html"})
            pptx = [Path(x["path"]) for x in found if x["kind"] == "pptx" and x.get("bytes")
                    and Path(x["path"]).parent == path.parent]
            if len(pptx) == 1:
                expected.add(pptx[0])
        groups.append([x for x in found if x.get("bytes") and Path(x["path"]) in expected])
    # Do not combine a PPTX from one draft with HTML from another project.
    return max(groups, key=lambda group: len({x["kind"] for x in group}), default=[])


def read_delivery(output, secrets):
    value = {"artifacts": artifacts(output), "selfReport": {}}
    report = output / "EVAL_RESULT.json"
    if report.exists() and not report.is_symlink():
        try:
            contents = json.loads(redact(report.read_text(), secrets))
            if isinstance(contents, dict):
                value["selfReport"] = contents
            else:
                value["selfReportError"] = "EVAL_RESULT.json must be a JSON object."
        except (ValueError, OSError):
            value["selfReportError"] = "EVAL_RESULT.json is not readable JSON."
    value["deliveryArtifacts"] = delivery_artifacts(value["artifacts"])
    return value


def process_table():
    """Process identity and ancestry only; never collect commands or environments."""
    try:
        rows = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,lstart="],
                              capture_output=True, text=True, timeout=2)
        table = {}
        for line in rows.stdout.splitlines():
            fields = line.split(maxsplit=3)
            if len(fields) == 4:
                pid, parent, group = map(int, fields[:3])
                table[pid] = {"parent": parent, "group": group, "started": fields[3]}
        return table
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


class ProcessTracker:
    """Remember detached descendants while their parent is still identifiable."""
    def __init__(self, proc):
        self.proc = proc
        self.known = {}
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.sample()
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    def sample(self):
        table = process_table()
        with self.lock:
            roots = {pid for pid, old in self.known.items()
                     if pid in table and self.same_process(old, table[pid])}
            if self.proc.poll() is None and self.proc.pid in table:
                roots.add(self.proc.pid)
            frontier = roots
            while frontier:
                for pid in frontier:
                    self.known[pid] = table[pid]
                children = {pid for pid, row in table.items() if row["parent"] in frontier} - roots
                roots.update(children)
                frontier = children
            return dict(self.known)

    @staticmethod
    def same_process(first, second):
        return first["started"] == second["started"] and first["group"] == second["group"]

    def _watch(self):
        while not self.done.wait(0.1):
            self.sample()

    def close(self):
        self.done.set()
        self.thread.join(timeout=3)


def stop_process(proc, tracker=None):
    owns_tracker = tracker is None
    tracker = tracker or ProcessTracker(proc)
    known = tracker.sample()
    # An unreaped live root PID belongs to this Popen and its private session.
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    # Do not signal stale PIDs or unrelated processes after reparenting/PID reuse.
    known.update(tracker.sample())
    current = process_table()
    for pid, identity in reversed(list(known.items())):
        if pid not in current or not ProcessTracker.same_process(identity, current[pid]):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if owns_tracker:
        tracker.close()


def run_process(command, cwd, env, secrets, timeout, log_dir, case_id):
    started = time.monotonic()
    metrics = {"firstEventSeconds": None, "firstTextSeconds": None, "assistantTurns": 0, "toolCalls": 0,
               "toolErrors": 0, "tokens": {}, "reportedCost": 0, "streamErrors": [], "agentEnded": False,
               "terminalStreamError": False, "lastStopReason": None, "lastRawStopReason": None,
               "contentFiltered": False,
               "toolTimings": [], "toolDurationSumSeconds": 0.0,
               "toolTimingNote": "Local monotonic event receipt intervals; sum includes matched finished calls only, may overlap, and is not wall-clock time."}
    try:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", start_new_session=True)
    except OSError as exc:
        return {"exitCode": None, "timedOut": False, "elapsedSeconds": 0,
                "executionError": redact(str(exc), secrets), **metrics}

    tracker = ProcessTracker(proc)

    def consume(stream, destination, parse):
        pending_tools = {}
        with Path(destination).open("w") as output:
            for line in iter(stream.readline, ""):
                received_seconds = round(time.monotonic() - started, 6)
                clean = redact(line, secrets)
                output.write(clean)
                output.flush()
                if not parse:
                    continue
                try:
                    event = json.loads(clean)
                except ValueError:
                    continue
                if metrics["firstEventSeconds"] is None:
                    metrics["firstEventSeconds"] = round(time.monotonic() - started, 3)
                kind = event.get("type")
                if kind == "message_update" and event.get("assistantMessageEvent", {}).get("type") == "text_delta" and event["assistantMessageEvent"].get("delta", "").strip() and metrics["firstTextSeconds"] is None:
                    metrics["firstTextSeconds"] = round(time.monotonic() - started, 3)
                if kind == "tool_execution_start":
                    metrics["toolCalls"] += 1
                    call_id = event.get("toolCallId")
                    record = {"toolCallId": call_id, "toolName": event.get("toolName"),
                              "startSeconds": received_seconds, "endSeconds": None,
                              "durationSeconds": None, "status": "pending", "isError": None}
                    metrics["toolTimings"].append(record)
                    if isinstance(call_id, str) and call_id:
                        pending_tools[call_id] = record
                elif kind == "tool_execution_end":
                    is_error = bool(event.get("isError"))
                    metrics["toolErrors"] += int(is_error)
                    call_id = event.get("toolCallId")
                    record = pending_tools.pop(call_id, None) if isinstance(call_id, str) else None
                    if record is None:
                        # No start means no measured duration; never invent a zero-length call.
                        record = {"toolCallId": call_id, "toolName": event.get("toolName"),
                                  "startSeconds": None, "durationSeconds": None, "status": "unmatched_end"}
                        metrics["toolTimings"].append(record)
                    else:
                        duration = round(received_seconds - record["startSeconds"], 6)
                        record.update(durationSeconds=duration, status="failed" if is_error else "completed")
                        metrics["toolDurationSumSeconds"] = round(metrics["toolDurationSumSeconds"] + duration, 6)
                    record.update(endSeconds=received_seconds, isError=is_error)
                elif kind in ("agent_start", "auto_retry_start"):
                    metrics["agentEnded"] = False
                elif kind == "agent_end":
                    metrics["agentEnded"] = not event.get("willRetry", False)
                elif kind == "message_end" and event.get("message", {}).get("role") == "assistant":
                    message = event["message"]
                    metrics["agentEnded"] = False
                    metrics["lastStopReason"] = message.get("stopReason")
                    metrics["lastRawStopReason"] = message.get("rawStopReason")
                    metrics["contentFiltered"] |= message.get("rawStopReason") == "content_filter"
                    # Keep recovered API errors as history without making a later
                    # successful assistant turn a terminal API failure.
                    metrics["terminalStreamError"] = message.get("stopReason") in ("error", "aborted")
                    metrics["assistantTurns"] += 1
                    usage = message.get("usage", {})
                    for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens"):
                        if isinstance(usage.get(key), (int, float)):
                            metrics["tokens"][key] = metrics["tokens"].get(key, 0) + usage[key]
                    metrics["reportedCost"] += usage.get("cost", {}).get("total", 0) or 0
                    if message.get("stopReason") in ("error", "aborted"):
                        metrics["streamErrors"].append(message.get("errorMessage", message["stopReason"]))
        stream.close()

    threads = [threading.Thread(target=consume, args=(proc.stdout, log_dir / "stdout.jsonl", True), daemon=True),
               threading.Thread(target=consume, args=(proc.stderr, log_dir / "stderr.log", False), daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = False
    next_heartbeat = started + 15
    try:
        while proc.poll() is None:
            now = time.monotonic()
            if STOP.is_set() or now - started >= timeout:
                timed_out = not STOP.is_set()
                stop_process(proc, tracker)
                break
            if now >= next_heartbeat:
                progress(f"[{case_id}] running {now - started:.0f}s, tools={metrics['toolCalls']}")
                next_heartbeat = now + 15
            time.sleep(min(0.2, max(0.01, timeout - (now - started))))
        proc.wait(timeout=3)
    finally:
        # Clean observed detached children even when pi itself exited successfully.
        stop_process(proc, tracker)
        tracker.close()
        for thread in threads:
            thread.join(timeout=3)
        if any(t.is_alive() for t in threads):
            stop_process(proc, tracker)
            for thread in threads:
                thread.join(timeout=1)
    return {"exitCode": proc.returncode, "timedOut": timed_out, "cancelled": STOP.is_set(),
            "elapsedSeconds": round(time.monotonic() - started, 3), **metrics}


def classify(execution, found, self_report, needs_input):
    if execution.get("cancelled"):
        return "cancelled"
    if execution.get("timedOut"):
        return "timed_out"
    if execution.get("exitCode") != 0 or execution.get("contentFiltered") or execution.get("terminalStreamError", bool(execution.get("streamErrors"))):
        return "execution_failed"
    if self_report.get("status") == "failed":
        return "author_reported_failure"
    if needs_input or self_report.get("status") == "needs_input":
        return "needs_input"
    kinds = {x["kind"] for x in found}
    if {"pptd", "pptx", "html"}.issubset(kinds) and execution.get("agentEnded"):
        return "generated_unreviewed"
    return "incomplete"


def merge_execution(result, execution, offset, attempt):
    """Aggregate measured work; each attempt also keeps its own local timings."""
    totals = {}
    for key in ("assistantTurns", "toolCalls", "toolErrors", "reportedCost", "toolDurationSumSeconds"):
        totals[key] = result.get(key, 0) + execution.get(key, 0)
    totals["tokens"] = dict(result.get("tokens", {}))
    for key, value in execution.get("tokens", {}).items():
        totals["tokens"][key] = totals["tokens"].get(key, 0) + value
    totals["streamErrors"] = result.get("streamErrors", []) + execution.get("streamErrors", [])
    totals["contentFiltered"] = result.get("contentFiltered", False) or execution.get("contentFiltered", False)
    totals["toolTimings"] = list(result.get("toolTimings", []))
    for record in execution.get("toolTimings", []):
        adjusted = dict(record, attempt=attempt)
        for key in ("startSeconds", "endSeconds"):
            if adjusted.get(key) is not None:
                adjusted[key] = round(adjusted[key] + offset, 6)
        totals["toolTimings"].append(adjusted)
    for key in ("firstEventSeconds", "firstTextSeconds"):
        totals[key] = result.get(key)
        if totals[key] is None and execution.get(key) is not None:
            totals[key] = round(offset + execution[key], 3)
    result.update(execution, **totals)


def continuation_reason(result, session, count, limit):
    if result["status"] != "incomplete":
        return "terminal_status"
    if not result.get("agentEnded") or result.get("lastStopReason") != "stop":
        return "not_normal_stop"
    if count >= limit:
        return "limit_reached"
    if not session.is_file() or not session.stat().st_size:
        return "session_unavailable"
    return None


def continuation_prompt(result, remaining):
    kinds = {x["kind"] for x in result["deliveryArtifacts"]}
    missing = ", ".join(sorted({"pptd", "pptx", "html"} - kinds)) or "完成事件/交付核对"
    return f"""继续同一用户任务和已有工作。上次正常停止，但正式交付仍缺：{missing}。
剩余整题时间约 {max(0, int(remaining))} 秒，原页数、内容深度、生成回合与检查要求保留。
复用已有 DESIGN_CONTEXT、来源、模块和页面，从未完成步骤继续；不要从头研究或重写已有成果。
通过 pi 的真实工具调用执行，普通文本中的工具调用标签没有执行效果；不要把上一条标签复制成 shell 命令。
正式三格式放 output/deck/，复用 skill 现有校验/渲染/导出命令；大内容按 quickstart 分模块写，每次带完整路径与内容。
缺少必要材料则明确记录 NEEDS_INPUT；明确无法完成则记录原因，不伪造或绕过接口拒绝。更新 output/EVAL_RESULT.json，并如实保留未完成检查。
"""


def run_case(case, run_dir, snapshot, config_source, base_env, secrets, options):
    case_started = time.monotonic()
    if STOP.is_set():
        return {"caseId": case["id"], "status": "cancelled", "elapsedSeconds": 0,
                "exitCode": None, "qualityStatus": "not_reviewed"}
    case_dir = run_dir / "cases" / case["id"]
    work = case_dir / "work"
    work.mkdir(parents=True)
    (work / "output").mkdir()
    copy_tree(snapshot, work / "skill")
    prompt = build_prompt(case, work / "skill", options.allow_web, options.model_inputs)
    (case_dir / "prompt.md").write_text(prompt)
    command = [options.pi, "--print", "--mode", "json", "--offline",
               "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes",
               "--no-context-files", "--no-approve", "--skill", str(work / "skill"),
               "--tools", "read,bash,edit,write,grep,find,ls", "--provider", options.provider,
               "--model", options.model]
    if options.thinking is not None:
        command.extend(["--thinking", options.thinking])
    base_command = command
    command = base_command + ["--session", "<private-per-case-session>", "--", "@" + str(case_dir / "prompt.md")]
    result = {"caseId": case["id"], "promptSha256": digest(case["prompt"].encode()),
              "expectedBehavior": case["expected_behavior"], "command": command,
              "qualityStatus": "not_reviewed", "selfReport": {}, "artifacts": [],
              "attempts": [], "continuationCount": 0}
    progress(f"[{case['id']}] {'prepared' if options.dry_run else 'started'}")
    if options.dry_run:
        result.update(status="dry_run", elapsedSeconds=0, exitCode=None)
    else:
        with tempfile.TemporaryDirectory(prefix="pi-eval-auth-") as private:
            cfg = Path(private) / "agent"
            copy_tree(config_source, cfg)
            cfg.chmod(0o700)
            env = dict(base_env, PI_CODING_AGENT_DIR=str(cfg))
            # Native pi session holds context only for this case. Raw session data
            # stays in the private temporary directory and is deleted with auth.
            session = Path(private) / "session.jsonl"
            started = time.monotonic()
            deadline = started + options.timeout
            prompt_path = case_dir / "prompt.md"
            attempt_dir = case_dir
            for index in range(options.max_continuations + 1):
                remaining = deadline - time.monotonic()
                if STOP.is_set() or remaining <= 0:
                    result.update(cancelled=STOP.is_set(), timedOut=not STOP.is_set(),
                                  status="cancelled" if STOP.is_set() else "timed_out",
                                  continuationStopReason="deadline_or_cancelled")
                    break
                command = base_command + ["--session", str(session), "--", "@" + str(prompt_path)]
                if index == 0:
                    result["command"] = command
                offset = time.monotonic() - started
                execution = run_process(command, work, env, secrets, remaining, attempt_dir, case["id"])
                merge_execution(result, execution, offset, index + 1)
                result.pop("selfReportError", None)
                result.update(read_delivery(work / "output", secrets))
                result["status"] = classify(result, result["deliveryArtifacts"], result["selfReport"],
                                            (work / "output" / "NEEDS_INPUT.md").exists())
                # Protocol-only completion; independent review still owns quality.
                result["continuationCount"] = index
                result["attempts"].append({"number": index + 1, "command": command,
                    "logDirectory": str(attempt_dir.relative_to(case_dir)), "startSeconds": round(offset, 6),
                    "timeoutSeconds": round(remaining, 6), "status": result["status"], **execution})
                reason = continuation_reason(result, session, index, options.max_continuations)
                if reason:
                    result["continuationStopReason"] = reason
                    break
                if inventory(work / "skill") != inventory(snapshot):
                    result.update(status="skill_mutated", continuationStopReason="skill_mutated")
                    break
                attempt_dir = case_dir / "attempts" / f"{index + 2:02d}"
                attempt_dir.mkdir(parents=True)
                prompt_path = attempt_dir / "prompt.md"
                prompt_path.write_text(continuation_prompt(result, deadline - time.monotonic()))
                progress(f"[{case['id']}] normal stop with missing delivery; continuation {index + 1}/{options.max_continuations}, remaining={max(0, deadline - time.monotonic()):.0f}s")
            result["elapsedSeconds"] = round(time.monotonic() - started, 3)
        # A model editing skill code invalidates comparison, even if outputs exist.
        result["skillUnchanged"] = inventory(work / "skill") == inventory(snapshot)
        if not result["skillUnchanged"]:
            result["status"] = "skill_mutated"
    result["caseElapsedSeconds"] = round(time.monotonic() - case_started, 3)
    write_json(case_dir / "result.json", result)
    write_json(case_dir / "review.json", {"caseId": case["id"], "status": "not_reviewed", "reviewer": None,
               "blockingFindings": [], "dimensions": {k: {"score": None, "evidence": []} for k in DIMENSIONS},
               "note": "Score only after reading slides, sources, images and exported files; null is not zero."})
    progress(f"[{case['id']}] {result['status']} {result['elapsedSeconds']:.1f}s")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-file", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--case", action="append", default=[], help="ID, numeric prefix, or tag; repeat/comma separate")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Snapshot and write prompts; do not call a model")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=3600, help="Shared hard seconds per case including continuations (default: 3600), excluding initial snapshot copy")
    parser.add_argument("--max-continuations", type=int, default=2, help="Resume normal stops with missing delivery at most N times; 0 disables (default: 2)")
    parser.add_argument("--output-root", type=Path, default=Path(tempfile.gettempdir()) / "open-pptd-pi-eval")
    parser.add_argument("--skill", type=Path, default=ROOT / "skills/open-pptd")
    parser.add_argument("--pi", default=shutil.which("pi") or "pi")
    parser.add_argument("--config-dir", type=Path, default=Path(os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent"))))
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--key-env", help="Name only; credentials are never passed on command line")
    parser.add_argument("--thinking", choices=["off", "minimal", "low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--allow-web", action="store_true", help="Allow public-source/image retrieval in case prompts")
    options = parser.parse_args(argv)
    STOP.clear()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda _signal, _frame: STOP.set())
    if options.concurrency < 1 or options.timeout <= 0:
        parser.error("--concurrency and --timeout must be positive")
    if options.max_continuations < 0:
        parser.error("--max-continuations must be nonnegative")
    all_cases = json.loads(options.cases_file.read_text())["cases"]
    selectors = [x.strip() for value in options.case for x in value.split(",") if x.strip()]
    matches = lambda c, value: c["id"] == value or c["id"].startswith(value + "-") or value in c.get("tags", [])
    if any(not any(matches(c, value) for c in all_cases) for value in selectors):
        parser.error("One or more case selectors match nothing; use --list")
    cases = [c for c in all_cases if not selectors or any(matches(c, value) for value in selectors)]
    if options.list:
        for case in cases:
            print(case["id"] + "\t" + ",".join(case["tags"]))
        return 0
    if options.output_root.resolve().is_relative_to(ROOT.resolve()):
        parser.error("--output-root must be outside this repository to protect real projects and snapshots")
    options.output_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-") , dir=options.output_root))
    run_dir.chmod(0o700)
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="pi-eval-config-") as private:
            config = Path(private) / "agent"
            env, secrets, options.provider, options.model = prepare_config(
                options.config_dir, config, options.provider, options.model, options.key_env, options.thinking)
            configured = json.loads((config / "models.json").read_text()) if (config / "models.json").exists() else {}
            selected_models = configured.get("providers", {}).get(options.provider, {}).get("models", [])
            options.model_inputs = next((m.get("input") for m in selected_models if m.get("id") == options.model), None)
            snapshot = run_dir / "snapshot" / "open-pptd"
            snapshot.parent.mkdir()
            snapshot_info = make_snapshot(options.skill.resolve(), snapshot)
            write_json(run_dir / "snapshot-manifest.json", snapshot_info)
            version = subprocess.run([options.pi, "--version"], capture_output=True, text=True,
                                     env=env, cwd=run_dir, timeout=15)
            metadata = {"schemaVersion": 1, "startedAt": datetime.now(timezone.utc).isoformat(),
                        "git": git_identity(ROOT), "snapshotSha256": snapshot_info["treeSha256"],
                        "casesSha256": digest(options.cases_file.read_bytes()),
                        "runnerSha256": digest(Path(__file__).read_bytes()),
                        "provider": options.provider, "model": options.model,
                        "thinking": options.thinking,
                        "effectiveThinking": json.loads((config / "settings.json").read_text()).get("defaultThinkingLevel"),
                        "piVersion": redact(version.stdout.strip(), secrets),
                        "pythonVersion": sys.version.split()[0], "concurrency": options.concurrency,
                        "timeoutSeconds": options.timeout, "timeoutScope": "case_including_continuations",
                        "maxContinuations": options.max_continuations, "modelInputs": options.model_inputs,
                        "allowWeb": options.allow_web,
                        "dryRun": options.dry_run, "caseIds": [c["id"] for c in cases],
                        "qualityStatus": "not_reviewed", "runDirectory": str(run_dir)}
            write_json(run_dir / "run.json", metadata)
            shutil.copy2(options.cases_file, run_dir / "cases.json")
            results = []
            with ThreadPoolExecutor(max_workers=options.concurrency) as pool:
                futures = {pool.submit(run_case, case, run_dir, snapshot, config, env, secrets, options): case for case in cases}
                for future in as_completed(futures):
                    case = futures[future]
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        value = {"caseId": case["id"], "status": "runner_error", "qualityStatus": "not_reviewed",
                                 "elapsedSeconds": None, "exitCode": None, "error": redact(str(exc), secrets)}
                        results.append(value)
                        case_dir = run_dir / "cases" / case["id"]
                        case_dir.mkdir(exist_ok=True, parents=True)
                        write_json(case_dir / "result.json", value)
                        progress(f"[{case['id']}] runner_error; see result.json")
            results.sort(key=lambda x: x["caseId"])
            metadata.update(elapsedSeconds=round(time.monotonic() - started, 3), results=results)
            metadata["runStatus"] = "completed" if all(x["status"] in ("dry_run", "generated_unreviewed", "needs_input") for x in results) else "completed_with_failures"
            write_json(run_dir / "summary.json", metadata)
            lines = ["# pi 固定用例运行记录", "", f"模型：{options.provider}/{options.model}；并发：{options.concurrency}；总耗时：{metadata['elapsedSeconds']}s。",
                     "", "以下是执行结果，所有用例的内容和视觉质量仍待独立评阅。needs_input 是否正确须结合缺材料的题目判断。", "",
                     "| Case | 状态 | 耗时（秒） | Exit |", "|---|---|---:|---:|"]
            lines += [f"| {r['caseId']} | {r['status']} | {r.get('elapsedSeconds')} | {r.get('exitCode')} |" for r in results]
            (run_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n")
            print(json.dumps({"runDirectory": str(run_dir), "runStatus": metadata["runStatus"], "qualityStatus": "not_reviewed"}))
            return 0 if metadata["runStatus"] == "completed" else 1
    except Exception as exc:
        write_json(run_dir / "runner-error.json", {"status": "runner_error", "errorType": type(exc).__name__})
        # Do not expose provider responses/config values through setup exceptions.
        progress(f"Runner setup failed ({type(exc).__name__}); no model results claimed. Run: {run_dir}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
