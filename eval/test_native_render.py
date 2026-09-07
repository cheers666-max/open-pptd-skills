import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent


def alive(pid):
    proc = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    return bool(proc.stdout.strip()) and not proc.stdout.strip().startswith("Z")


@unittest.skipUnless(importlib.util.find_spec("pymupdf") and importlib.util.find_spec("PIL"),
                     "Optional native-render dependencies unavailable")
class NativeRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-render-lifecycle-test-")
        self.run = Path(self.temp.name)
        (self.run / "run.json").write_text(json.dumps({"caseIds": ["01-probe"]}))
        self.case = self.run / "cases/01-probe"
        output = self.case / "work/output"
        output.mkdir(parents=True)
        (output / "deck.pptx").write_bytes(b"Controlled fake converter input; not a valid deck")
        self.pid_file = self.run / "converter.pid"
        self.fake = self.run / "fake-soffice"
        self.fake.write_text("#!" + sys.executable + "\nimport os,pathlib,time\npathlib.Path(" +
                             repr(str(self.pid_file)) + ").write_text(str(os.getpid()))\ntime.sleep(30)\n")
        self.fake.chmod(0o700)
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=3)
        if self.pid_file.exists():
            pid = int(self.pid_file.read_text())
            if alive(pid):
                os.kill(pid, signal.SIGKILL)
        self.temp.cleanup()

    def start(self, timeout=5):
        self.proc = subprocess.Popen([sys.executable, str(HERE / "render_pptx.py"), str(self.run),
                                      "--libreoffice", str(self.fake), "--timeout", str(timeout)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return self.proc

    def report(self):
        return json.loads((self.run / "native-render-summary.json").read_text())["01-probe"][0]

    def assert_child_stopped(self):
        # A very short timeout may terminate Python before its first fixture write.
        pid = int(self.pid_file.read_text()) if self.pid_file.exists() else self.report()["converterPid"]
        for _ in range(30):
            if not alive(pid):
                return
            time.sleep(.05)
        self.fail("Converter survived native renderer termination")

    def test_sigterm_cleans_converter_and_reports_cancelled(self):
        proc = self.start()
        deadline = time.monotonic() + 5
        while not self.pid_file.exists() and time.monotonic() < deadline and proc.poll() is None:
            time.sleep(.05)
        self.assertTrue(self.pid_file.exists())
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=8)
        self.assertEqual(proc.returncode, 1, stdout + stderr)
        self.assertFalse(json.loads(stdout)["allRendered"])
        self.assertEqual(self.report()["status"], "cancelled")
        self.assert_child_stopped()

    def test_timeout_cleans_converter_and_reports_unavailable(self):
        proc = self.start(timeout=.3)
        stdout, stderr = proc.communicate(timeout=8)
        self.assertEqual(proc.returncode, 1, stdout + stderr)
        self.assertEqual(self.report()["status"], "unavailable")
        self.assertIn("timed out", self.report()["error"])
        self.assert_child_stopped()

    def test_exit_zero_without_fresh_pdf_does_not_accept_earlier_render(self):
        old = self.case / "precheck/native-pptx/render-old"
        old.mkdir(parents=True)
        (old / "deck.pdf").write_bytes(b"stale prior render")
        self.fake.write_text("#!" + sys.executable + "\nraise SystemExit(0)\n")
        proc = self.start()
        stdout, stderr = proc.communicate(timeout=8)
        self.assertEqual(proc.returncode, 1, stdout + stderr)
        self.assertEqual(self.report()["status"], "unavailable")
        self.assertIn("this run's PDF", self.report()["error"])
        self.assertEqual((old / "deck.pdf").read_bytes(), b"stale prior render")


if __name__ == "__main__":
    unittest.main()
