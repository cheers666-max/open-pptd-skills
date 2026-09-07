import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("pi_review", HERE / "review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

FAKE_REVIEWER = r'''#!/usr/bin/env python3
import json,pathlib,sys
model=sys.argv[sys.argv.index("--model")+1]
assert sys.argv[sys.argv.index("--tools")+1] == "read,grep,find,ls"
path="work/output/pages/1.page"
pathlib.Path(path).read_text()
print(json.dumps({"type":"tool_execution_start","toolName":"read","toolCallId":"a","args":{"path":path}}))
print(json.dumps({"type":"tool_execution_end","toolCallId":"a","isError":False,"result":{"content":[{"type":"text","text":"content"}]}}))
dimensions={k:{"score":None,"evidence":[]} for k in ["request_fulfillment","factual_grounding","professional_depth","content_richness","image_relevance","layout_legibility","delivery_integrity","teaching_or_actionability"]}
dimensions["professional_depth"]={"score":3,"evidence":[{"file":path,"page":1,"observation":"Read page 1; only a small sample of depth."}]}
if model == "bad-facts":
    dimensions["factual_grounding"]={"score":5,"evidence":[{"file":path,"page":1,"observation":"unsupported certainty"}]}
candidate={"caseId":"20-dying-to-survive","status":"partially_reviewed","scope":"Only page 1 read; facts and visual formats not independently verified.","dimensions":dimensions,"blockingFindings":[]}
print(json.dumps({"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":json.dumps(candidate)}]}}))
print(json.dumps({"type":"agent_end","messages":[]}))
'''


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-precheck-test-")
        self.run = Path(self.temp.name)
        self.case_id = "20-dying-to-survive"
        self.case_dir = self.run / "cases" / self.case_id
        self.output = self.case_dir / "work/output"
        (self.output / "pages").mkdir(parents=True)
        self.case = json.loads((HERE / "cases.json").read_text())["cases"][-1]
        review.common.write_json(self.run / "cases.json", {"cases":[self.case]})
        review.common.write_json(self.run / "run.json", {"caseIds":[self.case_id], "provider":"fake", "model":"normal"})
        review.common.write_json(self.case_dir / "result.json", {"status":"generated_unreviewed"})
        review.common.write_json(self.case_dir / "review.json", {"status":"not_reviewed", "dimensions":{k:{"score":None,"evidence":[]} for k in review.common.DIMENSIONS}})
        for index in range(1,4):
            (self.output / "pages" / f"{index}.page").write_text("pageType: content\ntitle: Test\nelements: []\n")
        (self.output / "deck.pptd").write_text("title: fixture\nsize: [960, 540]\npages:\n  - pages/1.page\n  - pages/2.page\n  - pages/3.page\n")
        scripts = self.run / "snapshot/open-pptd/scripts"
        scripts.mkdir(parents=True)
        validator = scripts / "validate_deck.py"
        shutil.copy2(HERE.parent / "skills/open-pptd/scripts/validate_deck.py", validator)
        review.common.write_json(self.run / "snapshot-manifest.json", {"files":{"scripts/validate_deck.py":{"sha256":review.common.digest(validator.read_bytes())}}})
        with zipfile.ZipFile(self.output / "deck.pptx", "w") as archive:
            archive.writestr("ppt/presentation.xml", '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst><p:sldId id="1"/><p:sldId id="2"/></p:sldIdLst></p:presentation>')
            slide = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:pic/><a:latin typeface="Arial"/><a:t>Test</a:t></p:sld>'
            for i in range(1,3):
                archive.writestr(f"ppt/slides/slide{i}.xml", slide)
            archive.writestr("ppt/media/image1.png", b"fixture bytes; never claimed to be a valid image")
        (self.output / "index.html").write_text('<div class="stage"><div class="slide"></div></div><div class="stage"><div class="slide"></div></div>')
        review.common.write_json(self.output / "render.json", {"renderHealth":[{"ok":False,"errors":["chart failed"]}]})
        review.common.write_json(self.output / "EVAL_RESULT.json", {"notes":["Author says done"]})
        (self.output / "SOURCES.md").write_text("Source URLs only, not independently verified")
        self.config = self.run / "private-test-config"
        self.config.mkdir()
        review.common.write_json(self.config / "models.json", {"providers":{"fake":{"api":"openai-completions","baseUrl":"https://example.invalid","apiKey":"fixture-private-token","models":[{"id":"normal"},{"id":"bad-facts"}]}}})
        self.fake = self.run / "fake-pi"
        self.fake.write_text(FAKE_REVIEWER)
        self.fake.chmod(0o700)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args, expected_exit=0):
        proc = subprocess.run([sys.executable, str(HERE / "review.py"), str(self.run),
                               "--pi", str(self.fake), "--config-dir", str(self.config), *args],
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode,expected_exit,proc.stdout+proc.stderr)
        self.last_cli = json.loads(proc.stdout.strip().splitlines()[-1])
        return json.loads((self.run / "review-summary.json").read_text())

    def test_static_default_checks_counts_and_preserves_artifacts_and_null_scores(self):
        before = review.common.inventory(self.output)
        summary = self.invoke()
        report = summary["cases"][0]
        self.assertEqual(review.common.inventory(self.output), before)
        self.assertEqual(report["manifests"][0]["pageCount"],3)
        self.assertEqual(report["pptx"][0]["pageCount"],2)
        self.assertEqual(report["html"][0]["pageCount"],2)
        self.assertEqual(report["pptx"][0]["fonts"],["Arial"])
        self.assertEqual(report["pptx"][0]["mediaCount"],1)
        codes = {x["code"] for x in report["findings"]}
        self.assertEqual(codes,{"pptx-page-count-mismatch","html-page-count-mismatch","explicit-page-count-not-met"})
        self.assertTrue(report["renderReports"])
        self.assertEqual(report["review"]["status"],"not_reviewed")
        self.assertFalse((self.case_dir / "independent-review").exists())
        self.assertTrue(all(x["score"] is None for x in report["review"]["dimensions"].values()))

    def test_snapshot_validator_tamper_is_not_silently_accepted(self):
        (self.run / "snapshot/open-pptd/scripts/validate_deck.py").write_text("raise RuntimeError('changed')")
        report = review.inspect_case(self.run,self.case)
        self.assertEqual(report["manifests"][0]["validation"]["status"],"check_unavailable")
        self.assertEqual(report["manifests"][0]["pageCount"],3)

    def test_invalid_pptx_is_reported_as_unreadable(self):
        (self.output / "deck.pptx").write_text("not a zip")
        result = review.inspect_pptx(self.output / "deck.pptx",self.case_dir)
        self.assertEqual(result["status"],"unreadable")

    def test_scores_require_local_successfully_read_evidence(self):
        candidate = {"status":"partially_reviewed","dimensions":{"professional_depth":{"score":4,"evidence":[{"file":"work/output/pages/1.page","page":1,"observation":"specific"}]}}}
        problems = review.review_status(candidate,self.case_dir,{"filesRead":[],"imagesRead":[]})
        self.assertTrue(any("not successfully read" in x for x in problems))
        candidate["dimensions"]["professional_depth"]["evidence"][0]["file"]="../../outside.md"
        self.assertTrue(any("outside" in x for x in review.review_status(candidate,self.case_dir)))

    def test_visual_score_requires_an_actual_image_read(self):
        path = self.output / "overview.png"
        path.write_bytes(b"fixture")
        candidate={"status":"partially_reviewed","dimensions":{"layout_legibility":{"score":4,"evidence":[{"file":"work/output/overview.png","observation":"visual"}]}}}
        problems=review.review_status(candidate,self.case_dir,{"filesRead":[str(path)],"imagesRead":[]})
        self.assertTrue(any("no image" in x for x in problems))

    def test_explicit_pi_review_accepts_only_supported_partial_scores(self):
        summary=self.invoke("--pi-review", "--thinking", "low")
        result=summary["cases"][0]["review"]
        self.assertEqual(result["dimensions"]["professional_depth"]["score"],3)
        self.assertIsNone(result["dimensions"]["factual_grounding"]["score"])
        self.assertEqual(result["reviewer"]["mode"],"independent_read_only_local")
        self.assertEqual(result["reviewer"]["thinking"], "low")
        invocation=json.loads((self.case_dir / "independent-review/result.json").read_text())
        self.assertEqual(invocation["command"][invocation["command"].index("--thinking") + 1], "low")
        self.assertEqual(len(result["scopeEvidence"]["filesRead"]),1)
        # A second review does not overwrite an existing review unless explicitly allowed.
        second=self.invoke("--pi-review","--model","bad-facts")
        self.assertEqual(second["cases"][0]["review"],result)

    def test_pi_review_rejects_unverified_factual_score(self):
        summary=self.invoke("--pi-review","--model","bad-facts", expected_exit=1)
        self.assertEqual(summary["cases"][0]["review"]["status"],"not_reviewed")
        result=json.loads((self.case_dir / "independent-review/result.json").read_text())
        self.assertEqual(result["status"],"rejected")
        self.assertTrue(any("external fact verification" in x for x in result["validationProblems"]))
        self.assertEqual(self.last_cli["reviewStatus"], "failed")

    def test_changed_evidence_marks_review_stale_and_preserves_comments(self):
        self.invoke("--pi-review")
        before = (self.case_dir / "review.json").read_bytes()
        reviewed = json.loads(before)
        self.assertEqual(reviewed["evidenceHashes"]["work/output/pages/1.page"],
                         review.common.digest((self.output / "pages/1.page").read_bytes()))
        (self.output / "pages/1.page").write_text("pageType: content\ntitle: Changed after review\nelements: []\n")
        summary = self.invoke("--pi-review", expected_exit=1)
        self.assertEqual(summary["cases"][0]["reviewEvidenceStatus"], "stale")
        self.assertEqual(summary["cases"][0]["reviewAttempt"]["status"], "existing_review_invalid")
        self.assertEqual((self.case_dir / "review.json").read_bytes(), before)
        self.assertIn("未接受", (self.run / "REVIEW.md").read_text())

    def test_legacy_review_without_hashes_is_unbound_not_automatically_endorsed(self):
        self.invoke("--pi-review")
        record = json.loads((self.case_dir / "review.json").read_text())
        del record["evidenceHashes"]
        review.common.write_json(self.case_dir / "review.json", record)
        before = (self.case_dir / "review.json").read_bytes()
        summary = self.invoke()
        self.assertEqual(summary["cases"][0]["reviewEvidenceStatus"], "unbound")
        self.assertEqual((self.case_dir / "review.json").read_bytes(), before)

    def test_rejected_replacement_returns_failure_and_preserves_accepted_review(self):
        self.invoke("--pi-review")
        before = (self.case_dir / "review.json").read_bytes()
        summary = self.invoke("--pi-review", "--replace-review", "--model", "bad-facts", expected_exit=1)
        self.assertEqual((self.case_dir / "review.json").read_bytes(), before)
        self.assertEqual(summary["cases"][0]["reviewAttempt"]["status"], "rejected")
        self.assertEqual(self.last_cli["reviewStatus"], "failed")

    def test_evidence_changed_during_read_is_not_bound_to_new_bytes(self):
        self.fake.write_text(FAKE_REVIEWER.replace('pathlib.Path(path).read_text()',
            'pathlib.Path(path).read_text()\npathlib.Path(path).write_text("changed during review")'))
        summary = self.invoke("--pi-review", expected_exit=1)
        self.assertEqual(summary["cases"][0]["review"]["status"], "not_reviewed")
        attempt = json.loads((self.case_dir / "independent-review/result.json").read_text())
        self.assertNotIn("work/output/pages/1.page", attempt["candidate"]["evidenceHashes"])
        self.assertTrue(any("unbound evidence" in p for p in attempt["validationProblems"]))

    def test_non_object_author_report_does_not_abort_summary(self):
        (self.output / "EVAL_RESULT.json").write_text("[]")
        summary = self.invoke()
        self.assertEqual(summary["cases"][0]["authorReport"], {})
        self.assertIn("JSON object", summary["cases"][0]["authorReportError"])
        self.assertTrue((self.run / "REVIEW.md").is_file())


if __name__ == "__main__":
    unittest.main()
