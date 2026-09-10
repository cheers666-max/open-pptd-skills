import importlib.util
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("run_pi", HERE / "run_pi.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

FAKE_PI = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
if "--version" in sys.argv:
    print("fake-pi-1.0")
    sys.exit(0)
mode = sys.argv[sys.argv.index("--model") + 1]
out = pathlib.Path("output")
out.mkdir(exist_ok=True)
session = pathlib.Path(sys.argv[sys.argv.index("--session") + 1]) if "--session" in sys.argv else None
previous = json.loads(session.read_text()) if session and session.exists() else {}
attempt = previous.get("attempt", 0) + 1
if session:
    session.write_text(json.dumps({"attempt":attempt,"context":"original-task-context"}))
with (out / "invocations.jsonl").open("a") as invocations:
    invocations.write(json.dumps({"session":str(session),"attempt":attempt,"previousContext":previous.get("context")}) + "\n")
began = time.time()
print(json.dumps({"type":"session"}), flush=True)
print(json.dumps({"type":"message_update", "assistantMessageEvent":{"type":"text_delta", "delta":"start"}}), flush=True)
cfg = pathlib.Path(os.environ["PI_CODING_AGENT_DIR"])
models = json.loads((cfg / "models.json").read_text())
(out / "isolation.json").write_text(json.dumps({"config":str(cfg),"providerNames":list(models["providers"]),"unrelatedKeyPresent":"UNRELATED_API_KEY" in os.environ}))
if mode in ("resume", "always-stop", "slow-stop", "prototype", "recovered-stop", "content-filter", "author-failed", "no-agent-end", "length-stop", "no-session-file", "retry-no-final-end", "broken-stream-with-progress", "tool-use-stop"):
    def event(value):
        print(json.dumps(value),flush=True)
    if mode == "slow-stop":
        time.sleep(.45)
    if mode == "retry-no-final-end":
        event({"type":"message_end","message":{"role":"assistant","stopReason":"error","errorMessage":"temporary error"}})
        event({"type":"agent_end","willRetry":True,"messages":[]})
        event({"type":"agent_start"})
    if mode in ("content-filter", "recovered-stop"):
        event({"type":"message_end","message":{"role":"assistant","stopReason":"error","rawStopReason":"content_filter" if mode == "content-filter" else "error","errorMessage":"provider failed"}})
        if mode == "recovered-stop":
            event({"type":"auto_retry_end","success":True})
    if mode == "content-filter":
        event({"type":"agent_end","messages":[]})
        sys.exit(0)
    if mode == "author-failed":
        (out / "EVAL_RESULT.json").write_text(json.dumps({"status":"failed"}))
    if mode == "prototype":
        for name in [".pattern-test/deck.pptd",".pattern-test/deck.pptx",".pattern-test/index.html","research/saved.html"]:
            file = out / name
            file.parent.mkdir(parents=True,exist_ok=True)
            file.write_text("experiment, not delivery")
    if mode == "resume" and previous.get("context") == "original-task-context":
        for name in ["deck.pptd","deck.pptx","index.html"]:
            (out / name).write_text("fake artifact, intentionally not a valid slide format")
    if mode == "no-session-file" and session:
        session.unlink()
    if mode == "broken-stream-with-progress":
        if attempt == 1:
            (out / "deck").mkdir(exist_ok=True)
            (out / "deck" / "outline.json").write_text(json.dumps({"pages":[{"actionTitle":"planned"}]}))
            event({"type":"message_end","message":{"role":"assistant","stopReason":"error","rawStopReason":"error","errorMessage":"Stream ended without finish_reason"}})
            event({"type":"agent_end","messages":[]})
            sys.exit(1)
        for name in ["deck.pptd","deck.pptx","index.html"]:
            (out / name).write_text("fake artifact, intentionally not a valid slide format")
    event({"type":"message_end","message":{"role":"assistant","stopReason":"toolUse" if mode == "tool-use-stop" else "length" if mode == "length-stop" else "stop","rawStopReason":"length" if mode == "length-stop" else "stop","content":[{"type":"text","text":"<tool_call>write is plain text, not a dispatched tool</tool_call>"}],"usage":{"input":10,"output":7,"totalTokens":17}}})
    if mode not in ("no-agent-end", "retry-no-final-end"):
        event({"type":"agent_end","messages":[]})
elif mode == "timeout":
    child = subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],start_new_session=True)
    (out / "child.pid").write_text(str(child.pid))
    time.sleep(60)
elif mode == "api-error":
    print(json.dumps({"type":"message_end","message":{"role":"assistant","stopReason":"error","errorMessage":"provider failed"}}),flush=True)
elif mode == "needs-input":
    (out / "NEEDS_INPUT.md").write_text("Missing script")
    print(json.dumps({"type":"agent_end","messages":[]}),flush=True)
elif mode == "tool-timing":
    def event(value):
        print(json.dumps(value),flush=True)
    event({"type":"tool_execution_start","toolCallId":"success","toolName":"read","args":{"path":"private-argument-marker"}})
    event({"type":"tool_execution_start","toolCallId":"failure","toolName":"bash","args":{"command":"private-command-marker"}})
    time.sleep(.25)
    event({"type":"tool_execution_end","toolCallId":"failure","toolName":"bash","isError":True,"result":{"content":[{"type":"text","text":"private-result-marker"}]}})
    time.sleep(.25)
    event({"type":"tool_execution_end","toolCallId":"success","toolName":"read","isError":False,"result":{"content":[{"type":"text","text":"private-result-marker"}]}})
    event({"type":"tool_execution_start","toolCallId":"unfinished","toolName":"write","args":{"content":"private-write-marker"}})
    event({"type":"tool_execution_end","toolCallId":"unmatched","toolName":"read","isError":False})
    event({"type":"agent_end","messages":[]})
else:
    if mode == "background":
        child = subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        (out / "child.pid").write_text(str(child.pid))
    time.sleep(.35)
    for name in ["deck.pptd","deck.pptx","index.html"]:
        (out / name).write_text("fake artifact, intentionally not a valid slide format")
    (out / "timing.json").write_text(json.dumps({"start":began,"end":time.time()}))
    (out / "scan-roots.txt").write_text(os.environ.get("PI_EVAL_SCAN_ROOTS",""))
    if mode == "bad-self-report":
        (out / "EVAL_RESULT.json").write_text("[]")
    key_ref = models["providers"]["fake"]["apiKey"]
    print(os.environ.get(key_ref.lstrip("$"),""),file=sys.stderr,flush=True)
    print(json.dumps({"type":"tool_execution_start","toolName":"write"}),flush=True)
    print(json.dumps({"type":"message_end","message":{"role":"assistant","usage":{"input":10,"output":7,"totalTokens":17,"cost":{"total":.01}}}}),flush=True)
    print(json.dumps({"type":"agent_end","messages":[]}),flush=True)
'''


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-eval-test-")
        self.root = Path(self.temp.name)
        self.skill = self.root / "skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text("---\nname: open-pptd\ndescription: Test\n---\nTest skill")
        self.config = self.root / "global-config"
        self.config.mkdir()
        runner.write_json(self.config / "settings.json", {"defaultProvider":"fake", "defaultModel":"normal", "extensions":["do-not-load.ts"]})
        runner.write_json(self.config / "models.json", {"providers": {
            "fake": {"baseUrl":"https://example.invalid", "api":"openai-completions", "apiKey":"PI_EVAL_TEST_KEY", "models":[{"id":m} for m in ["normal","timeout","api-error","needs-input","background","bad-self-report","tool-timing","resume","always-stop","slow-stop","prototype","recovered-stop","content-filter","author-failed","no-agent-end","length-stop","no-session-file","broken-stream-with-progress","tool-use-stop"]]},
            "unrelated": {"apiKey":"DO-NOT-COPY-THIS-SECRET", "models":[]}}})
        self.fake = self.root / "fake-pi"
        self.fake.write_text(FAKE_PI)
        self.fake.chmod(0o700)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        command = [sys.executable, str(HERE / "run_pi.py"), "--skill", str(self.skill),
                   "--config-dir", str(self.config), "--pi", str(self.fake),
                   "--output-root", str(self.root / "runs"), "--timeout", "5", *args]
        env = dict(os.environ, PI_EVAL_TEST_KEY="runner-secret-123456", UNRELATED_API_KEY="unrelated-private-key")
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=20)
        self.assertIn(result.returncode, (0,1), result.stderr)
        path = Path(json.loads(result.stdout.strip().splitlines()[-1])["runDirectory"])
        return result, path, json.loads((path / "summary.json").read_text())

    def test_twenty_original_cases_and_expected_missing_inputs(self):
        cases = json.loads((HERE / "cases.json").read_text())["cases"]
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({c["id"] for c in cases}), 20)
        self.assertEqual(cases[-1]["prompt"], "生成ppt介绍我不是药神这部电影10页")
        self.assertIn("missing-materials", cases[7]["tags"])
        self.assertIn("premise-verification", cases[17]["tags"])
        self.assertIn("satire", cases[18]["tags"])

    def test_parallel_execution_is_not_a_quality_pass_and_is_isolated(self):
        config_before = (self.config / "models.json").read_bytes()
        result, path, summary = self.invoke("--case","01,02","--concurrency","2")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(summary["qualityStatus"], "not_reviewed")
        starts_ends = []
        for item in summary["results"]:
            self.assertEqual(item["status"], "generated_unreviewed")
            self.assertEqual(item["tokens"]["totalTokens"], 17)
            self.assertEqual(item["toolCalls"], 1)
            self.assertTrue(item["skillUnchanged"])
            folder = path / "cases" / item["caseId"]
            evidence = json.loads((folder / "work/output/isolation.json").read_text())
            self.assertEqual(evidence["providerNames"], ["fake"])
            self.assertFalse(evidence["unrelatedKeyPresent"])
            self.assertFalse(Path(evidence["config"]).exists())
            log = (folder / "stderr.log").read_text()
            self.assertNotIn("runner-secret-123456", log)
            self.assertIn("[REDACTED]", log)
            review = json.loads((folder / "review.json").read_text())
            self.assertTrue(all(x["score"] is None for x in review["dimensions"].values()))
            starts_ends.append(json.loads((folder / "work/output/timing.json").read_text()))
        self.assertLess(max(x["start"] for x in starts_ends), min(x["end"] for x in starts_ends))
        self.assertEqual((self.config / "models.json").read_bytes(), config_before)
        changed = path / "cases" / summary["results"][0]["caseId"] / "work/skill/SKILL.md"
        changed.write_text("changed in this copy")
        self.assertNotEqual(changed.read_text(), (path / "snapshot/open-pptd/SKILL.md").read_text())
        self.assertNotEqual(changed.read_text(), (self.skill / "SKILL.md").read_text())

    def test_timeout_kills_detached_pi_bash_descendant(self):
        result, path, summary = self.invoke("--case","03","--model","timeout","--timeout","0.4")
        item = summary["results"][0]
        self.assertEqual(item["status"], "timed_out")
        self.assertLess(item["elapsedSeconds"], 5)
        child = int((path / "cases" / item["caseId"] / "work/output/child.pid").read_text())
        for _ in range(30):
            probe = subprocess.run(["ps","-p",str(child),"-o","stat="], capture_output=True, text=True)
            if not probe.stdout.strip() or probe.stdout.strip().startswith("Z"):
                break
            time.sleep(.05)
        else:
            self.fail("Detached child survived timeout")

    def test_json_api_error_overrides_exit_zero(self):
        _, _, summary = self.invoke("--case","03","--model","api-error")
        self.assertEqual(summary["results"][0]["exitCode"], 0)
        self.assertEqual(summary["results"][0]["status"], "execution_failed")

    def test_premature_stop_continues_the_same_private_session(self):
        _, path, summary = self.invoke("--case", "20", "--model", "resume")
        item = summary["results"][0]
        self.assertEqual(item["status"], "generated_unreviewed")
        self.assertEqual(item["continuationCount"], 1)
        self.assertEqual([a["status"] for a in item["attempts"]], ["incomplete", "generated_unreviewed"])
        self.assertEqual(item["tokens"]["totalTokens"], 34)
        self.assertEqual(item["toolCalls"], 0, "Plain-text tool_call must not be dispatched by runner")
        folder = path / "cases" / item["caseId"]
        invocations = [json.loads(line) for line in (folder / "work/output/invocations.jsonl").read_text().splitlines()]
        self.assertEqual(invocations[0]["session"], invocations[1]["session"])
        self.assertEqual(invocations[1]["previousContext"], "original-task-context")
        self.assertFalse(Path(invocations[0]["session"]).exists(), "Raw session must be private and temporary")
        self.assertTrue((folder / "attempts/02/stdout.jsonl").exists())
        self.assertIn("<tool_call>", (folder / "stdout.jsonl").read_text())

    def test_continuations_are_finite_and_can_be_disabled(self):
        for limit in (0, 2):
            with self.subTest(limit=limit):
                _, _, summary = self.invoke("--case", "20", "--model", "always-stop", "--max-continuations", str(limit))
                item = summary["results"][0]
                self.assertEqual(item["status"], "incomplete")
                self.assertEqual(item["continuationCount"], limit)
                self.assertEqual(len(item["attempts"]), limit + 1)
                self.assertEqual(item["continuationStopReason"], "limit_reached")

    def test_all_continuations_share_one_deadline(self):
        _, _, summary = self.invoke("--case", "20", "--model", "slow-stop", "--timeout", "0.9")
        item = summary["results"][0]
        self.assertEqual(item["status"], "timed_out")
        self.assertEqual(item["continuationCount"], 1)
        self.assertLess(item["attempts"][1]["timeoutSeconds"], .45)
        self.assertLess(item["elapsedSeconds"], 1.8)

    def test_terminal_outcomes_and_incomplete_protocol_do_not_continue(self):
        for model, expected in [("normal", "generated_unreviewed"), ("needs-input", "needs_input"),
                                ("api-error", "execution_failed"), ("content-filter", "execution_failed"),
                                ("author-failed", "author_reported_failure"), ("no-agent-end", "incomplete"),
                                ("no-session-file", "incomplete")]:
            with self.subTest(model=model):
                _, path, summary = self.invoke("--case", "20", "--model", model)
                item = summary["results"][0]
                self.assertEqual(item["status"], expected)
                self.assertEqual(item["continuationCount"], 0)
                calls = (path / "cases" / item["caseId"] / "work/output/invocations.jsonl").read_text().splitlines()
                self.assertEqual(len(calls), 1)

    def test_a_turn_cut_off_at_the_output_limit_gets_another_turn(self):
        """A length stop is work in progress, not an abandoned case.

        The model was mid-action when the budget ran out; ending the case there throws away the
        pages it had already written. The continuation says so and asks for a smaller step.
        """
        _, path, summary = self.invoke("--case", "20", "--model", "length-stop", "--max-continuations", "1")
        item = summary["results"][0]
        self.assertEqual(item["status"], "incomplete")
        self.assertEqual(item["continuationCount"], 1)
        calls = (path / "cases" / item["caseId"] / "work/output/invocations.jsonl").read_text().splitlines()
        self.assertEqual(len(calls), 2)
        follow_up = (path / "cases" / item["caseId"] / "attempts/02/prompt.md").read_text()
        self.assertIn("必须以一次真实的工具调用开始", follow_up)
        self.assertNotIn("<tool_call>", follow_up, "Naming the marker teaches a weak model to print it")
        self.assertIn("被截断", follow_up)

    def test_a_stream_that_dies_over_landed_work_gets_another_turn(self):
        """A broken stream is not an empty case when a plan is already on disk.

        Case 20 of the ds4.1 batch died this way after 30 turns: outline and image pool were
        written, the gateway cut the stream, and the runner threw all of it away. The work on
        disk is what makes the next turn cheap, so it decides whether the case is continuable.
        """
        _, path, summary = self.invoke("--case", "20", "--model", "broken-stream-with-progress",
                                       "--max-continuations", "1")
        item = summary["results"][0]
        self.assertEqual(item["continuationCount"], 1)
        calls = (path / "cases" / item["caseId"] / "work/output/invocations.jsonl").read_text().splitlines()
        self.assertEqual(len(calls), 2)
        follow_up = (path / "cases" / item["caseId"] / "attempts/02/prompt.md").read_text()
        self.assertIn("断流", follow_up)
        self.assertNotIn("上次正常停止", follow_up)

    def test_a_broken_stream_with_nothing_on_disk_stays_a_failure(self):
        _, _, summary = self.invoke("--case", "20", "--model", "api-error", "--max-continuations", "1")
        item = summary["results"][0]
        self.assertEqual(item["status"], "execution_failed")
        self.assertEqual(item["continuationCount"], 0)

    def test_a_turn_that_ended_asking_for_a_tool_gets_another_turn(self):
        """The dispatch never happened, so the work is mid-action, not abandoned."""
        _, _, summary = self.invoke("--case", "20", "--model", "tool-use-stop", "--max-continuations", "1")
        item = summary["results"][0]
        self.assertEqual(item["continuationCount"], 1)

    def test_recovered_stream_error_is_history_not_terminal_failure(self):
        _, _, summary = self.invoke("--case", "20", "--model", "recovered-stop", "--max-continuations", "1")
        item = summary["results"][0]
        self.assertEqual(item["status"], "incomplete")
        self.assertEqual(item["continuationCount"], 1)
        self.assertEqual(item["streamErrors"], ["provider failed", "provider failed"])
        self.assertFalse(item["terminalStreamError"])

    def test_experiments_and_saved_research_are_not_formal_delivery(self):
        _, _, summary = self.invoke("--case", "20", "--model", "prototype", "--max-continuations", "1")
        item = summary["results"][0]
        self.assertEqual(item["status"], "incomplete")
        self.assertEqual(item["continuationCount"], 1)
        self.assertGreater(len(item["artifacts"]), 0, "Keep raw inventory as evidence")
        self.assertEqual(item["deliveryArtifacts"], [])

    def test_exported_html_directory_counts_but_unrelated_projects_do_not_combine(self):
        def found(*names):
            return [{"path": name, "kind": Path(name).suffix[1:], "bytes": 10} for name in names]
        full = runner.delivery_artifacts(found("deck/deck.pptd", "deck/deck.pptx", "deck/html/index.html", "deck/html/page_01.html"))
        self.assertEqual({x["kind"] for x in full}, {"pptd", "pptx", "html"})
        split = runner.delivery_artifacts(found("first.pptd", "first.pptx", "deck/second.pptd", "deck/html/index.html"))
        self.assertLess(len({x["kind"] for x in split}), 3)
        missing_manifest = runner.delivery_artifacts(found("deck/deck.pptx", "deck/html/index.html", "research/source.html"))
        self.assertEqual(missing_manifest, [])

    def test_generic_html_is_ambiguous_with_multiple_manifests(self):
        files = [{"path": name, "kind": Path(name).suffix[1:], "bytes": 10}
                 for name in ("deck/one.pptd", "deck/one.pptx", "deck/two.pptd", "deck/html/index.html")]
        self.assertNotIn("html", {x["kind"] for x in runner.delivery_artifacts(files)})

    def test_unique_custom_pptx_name_in_single_project_is_recognized(self):
        files = [{"path": name, "kind": Path(name).suffix[1:], "bytes": 10}
                 for name in ("deck/deck.pptd", "deck/slides.pptx", "deck/html/index.html")]
        self.assertEqual({x["kind"] for x in runner.delivery_artifacts(files)}, {"pptd", "pptx", "html"})

    def test_retry_agent_end_does_not_replace_final_agent_end(self):
        _, _, summary = self.invoke("--case", "20", "--model", "retry-no-final-end")
        item = summary["results"][0]
        self.assertEqual(item["status"], "incomplete")
        self.assertFalse(item["agentEnded"])
        self.assertEqual(item["continuationCount"], 0)

    def test_normal_exit_cleans_observed_detached_child_but_not_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        child = None
        try:
            _, path, summary = self.invoke("--case", "03", "--model", "background")
            item = summary["results"][0]
            self.assertEqual(item["status"], "generated_unreviewed")
            child = int((path / "cases" / item["caseId"] / "work/output/child.pid").read_text())
            for _ in range(30):
                probe = subprocess.run(["ps", "-p", str(child), "-o", "stat="], capture_output=True, text=True)
                if not probe.stdout.strip() or probe.stdout.strip().startswith("Z"):
                    break
                time.sleep(.05)
            else:
                self.fail("Detached child survived normal pi exit")
            self.assertIsNone(unrelated.poll(), "Cleanup must not kill an unrelated process")
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=3)
            if child:
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_cleanup_does_not_signal_a_reused_pid(self):
        from types import SimpleNamespace
        proc = SimpleNamespace(pid=12345, poll=lambda: 0)
        tracker = SimpleNamespace(sample=lambda: {12346:{"started":"old", "group":12346}})
        with patch.object(runner, "process_table", return_value={12346:{"started":"new", "group":12346}}), \
                patch.object(runner.os, "kill") as kill, patch.object(runner.os, "killpg") as killpg:
            runner.stop_process(proc, tracker)
            kill.assert_not_called()
            killpg.assert_not_called()

    def test_non_object_self_report_is_recorded_without_losing_case(self):
        _, _, summary = self.invoke("--case", "03", "--model", "bad-self-report")
        item = summary["results"][0]
        self.assertEqual(item["selfReport"], {})
        self.assertIn("JSON object", item["selfReportError"])
        self.assertEqual(item["status"], "generated_unreviewed")

    def test_tool_timings_match_local_receipts_without_recording_content(self):
        _, path, summary = self.invoke("--case", "03", "--model", "tool-timing")
        item = summary["results"][0]
        records = {x["toolCallId"]: x for x in item["toolTimings"]}
        success, failure = records["success"], records["failure"]
        self.assertEqual(success["status"], "completed")
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(item["toolErrors"], 1)
        for record in (success, failure):
            self.assertGreaterEqual(record["startSeconds"], 0)
            self.assertGreater(record["endSeconds"], record["startSeconds"])
            self.assertLessEqual(record["endSeconds"], item["elapsedSeconds"] + .001)
            self.assertAlmostEqual(record["durationSeconds"], record["endSeconds"] - record["startSeconds"], places=5)
            self.assertNotIn("args", record)
            self.assertNotIn("result", record)
        self.assertLess(failure["endSeconds"], success["endSeconds"])
        self.assertAlmostEqual(item["toolDurationSumSeconds"], success["durationSeconds"] + failure["durationSeconds"], places=5)
        span = max(x["endSeconds"] for x in (success, failure)) - min(x["startSeconds"] for x in (success, failure))
        self.assertGreater(item["toolDurationSumSeconds"], span, "Overlapping durations are a sum, not wall clock time")
        self.assertIn("overlap", item["toolTimingNote"])
        self.assertEqual(records["unfinished"]["status"], "pending")
        self.assertIsNone(records["unfinished"]["endSeconds"])
        self.assertIsNone(records["unfinished"]["durationSeconds"])
        self.assertEqual(records["unmatched"]["status"], "unmatched_end")
        self.assertIsNone(records["unmatched"]["startSeconds"])
        self.assertIsNone(records["unmatched"]["durationSeconds"])
        self.assertNotIn("private-", json.dumps(item["toolTimings"]))
        saved = json.loads((path / "cases" / item["caseId"] / "result.json").read_text())
        self.assertEqual(saved["toolTimings"], item["toolTimings"])

    def test_no_tool_events_and_legacy_results_remain_compatible(self):
        _, _, summary = self.invoke("--case", "08", "--model", "needs-input")
        item = summary["results"][0]
        self.assertEqual(item["toolTimings"], [])
        self.assertEqual(item["toolDurationSumSeconds"], 0)
        self.assertEqual(item["status"], "needs_input")
        legacy = {"exitCode": 0, "agentEnded": True}
        self.assertEqual(runner.classify(legacy, [{"kind": k} for k in ("pptd", "pptx", "html")], {}, False),
                         "generated_unreviewed")

    def test_missing_input_is_explicit_not_invented_success(self):
        _, _, summary = self.invoke("--case","08","--model","needs-input")
        self.assertEqual(summary["results"][0]["status"], "needs_input")
        self.assertEqual(summary["qualityStatus"], "not_reviewed")

    def test_dry_run_does_not_invoke_generation(self):
        _, path, summary = self.invoke("--case","20","--dry-run")
        self.assertEqual(summary["results"][0]["status"], "dry_run")
        self.assertFalse((path / "cases/20-dying-to-survive/stdout.jsonl").exists())
        self.assertNotIn("--thinking", summary["results"][0]["command"])
        self.assertIsNone(summary["thinking"])

    def test_explicit_thinking_is_recorded_and_passed(self):
        _, _, summary = self.invoke("--case", "03", "--thinking", "low")
        self.assertEqual(summary["thinking"], "low")
        self.assertEqual(summary["effectiveThinking"], "low")
        command = summary["results"][0]["command"]
        self.assertEqual(command[command.index("--thinking") + 1], "low")

    def test_generation_loads_the_scan_guard(self):
        """Both halves must be wired: an unset root list makes the guard allow everything."""
        _, path, summary = self.invoke("--case", "03")
        command = summary["results"][0]["command"]
        self.assertEqual(command[command.index("--extension") + 1], str(HERE / "scan_guard.js"))
        work = path / "cases/03-elevator-basketball/work"
        self.assertEqual((work / "output/scan-roots.txt").read_text(), str(work.resolve()))

    def test_snapshot_rejects_external_symlinks(self):
        (self.skill / "outside").symlink_to(self.config / "models.json")
        with self.assertRaisesRegex(ValueError, "external symlink"):
            runner.inventory(self.skill)

    def test_credential_commands_do_not_run(self):
        runner.write_json(self.config / "models.json", {"providers":{"fake":{"apiKey":"!echo must-not-run", "models":[{"id":"normal"}]}}})
        with self.assertRaisesRegex(ValueError, "Credential commands"):
            runner.prepare_config(self.config, self.root / "private", None, None)


if __name__ == "__main__":
    unittest.main()


class PassEnvTests(unittest.TestCase):
    def test_pass_env_forwards_named_variables_and_redacts_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            (source / "models.json").write_text(json.dumps({"providers": {"p": {"apiKey": "static-key-value", "models": [{"id": "m"}]}}}))
            with patch.dict(os.environ, {"IMG_SEARCH_KEY": "img-secret-123", "UNRELATED": "x"}):
                env, secrets, provider, model = runner.prepare_config(source, Path(tmp) / "dst", "p", "m", pass_env=["IMG_SEARCH_KEY", "MISSING_VAR"])
            self.assertEqual(env.get("IMG_SEARCH_KEY"), "img-secret-123")
            self.assertNotIn("UNRELATED", env)
            self.assertNotIn("MISSING_VAR", env)
            self.assertIn("img-secret-123", secrets)
            self.assertNotIn("img-secret-123", runner.redact("token img-secret-123 here", secrets))
