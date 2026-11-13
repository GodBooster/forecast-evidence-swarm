"""The static demo page (docs/demo) shows only data that is already public and correct.

Checks that its data files agree with the committed testnet evidence and the documented
live AI run, and that the browser hash rule reproduces the on-chain digest. If Node.js is
installed, the page's own JavaScript is also run against both control hashes.
"""

import copy
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from forecast_swarm.evidence import commitment

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "docs" / "demo"
EVIDENCE = ROOT / "docs" / "evidence" / "testnet-2026-11-09"
ORIGINAL = "ebb69f520eba9d71005afb006b731b251f41e4511fe10657263b96ef39509319"
CHANGED = "e757b2cf109a904140b2518e90a20572fe0702e78285f6766d9241ee3af6de75"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class DemoPageDataTests(unittest.TestCase):
    def test_delivery_is_the_accepted_testnet_delivery(self):
        self.assertEqual((DEMO / "data" / "delivery-job0.json").read_bytes(),
                         (EVIDENCE / "deliveries" / "a.json").read_bytes())
        delivery = load(DEMO / "data" / "delivery-job0.json")
        self.assertEqual(commitment("bundle", delivery["content"]), ORIGINAL)
        changed = copy.deepcopy(delivery["content"])
        self.assertEqual(changed["inputs"]["evidence"][0]["yes_count"], 15)
        changed["inputs"]["evidence"][0]["yes_count"] = 16
        self.assertEqual(commitment("bundle", changed), CHANGED)

    def test_receipt_matches_the_recorded_chain_snapshot_and_run_log(self):
        receipt = load(DEMO / "data" / "receipt.json")
        snapshot = load(EVIDENCE / "chain-snapshot.json")
        job = snapshot["jobs"]["0"]
        self.assertEqual(receipt["artifact_sha256"], job["artifact_sha256"])
        self.assertEqual(receipt["artifact_sha256"], ORIGINAL)
        for key in ("customer", "worker", "status", "publication_consent", "order_sha256"):
            self.assertEqual(receipt[key], job[key], key)
        self.assertEqual(receipt["reward_yocto"], job["reward"])
        self.assertEqual(receipt["contract_id"], snapshot["contract_id"])
        self.assertEqual(receipt["snapshot"]["block_height"], snapshot["block_height"])
        accept = [e for e in load(EVIDENCE / "run-log.json")["entries"]
                  if e.get("job_id") == 0 and e.get("method") == "accept"]
        self.assertEqual(len(accept), 1)
        self.assertEqual(receipt["accept_tx"], accept[0]["tx_hash"])
        self.assertTrue(receipt["accept_explorer"].endswith("/txns/" + accept[0]["tx_hash"]))

    def test_forecast_card_matches_the_documented_live_run(self):
        forecast = load(DEMO / "data" / "forecast.json")
        validation = (ROOT / "docs" / "VALIDATION.md").read_text(encoding="utf-8")
        row = next(line for line in validation.splitlines() if line.startswith("| `valid_wrong` | 15/20 YES"))
        self.assertIn(f"{forecast['probability_bps']} bps", row)
        self.assertIn("interval {}–{}".format(*forecast["interval_bps"]), row)
        self.assertIn(forecast["evidence_id"], row)
        self.assertIn(forecast["delivery_sha256"], row)
        self.assertIsNone(forecast["attestation"])
        self.assertEqual(forecast["outcome"], "NO")
        self.assertEqual((forecast["yes_count"], forecast["sample_count"]), (15, 20))

    def test_public_demo_folder_holds_only_the_page_and_its_data(self):
        files = sorted(str(p.relative_to(DEMO)) for p in DEMO.rglob("*") if p.is_file())
        self.assertEqual(files, ["data/delivery-job0.json", "data/forecast.json", "data/receipt.json",
                                 "demo.css", "demo.js", "index.html"])

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_page_javascript_reproduces_both_control_hashes(self):
        script = r"""
const fs = require("fs"); global.window = {}; global.document = undefined;
eval(fs.readFileSync(process.argv[1] + "/demo.js", "utf8"));
const b = JSON.parse(fs.readFileSync(process.argv[1] + "/data/delivery-job0.json", "utf8"));
(async () => {
  const o = await window.FES.commitment("bundle", b.content);
  const c = structuredClone(b.content); c.inputs.evidence[0].yes_count = 16;
  const t = await window.FES.commitment("bundle", c);
  console.log(JSON.stringify([o, t, window.FES.compare(undefined, o), window.FES.compare(o, t)]));
})();
"""
        out = subprocess.run(["node", "-e", script, str(DEMO)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), [ORIGINAL, CHANGED, "UNAVAILABLE", "MISMATCH"])


if __name__ == "__main__":
    unittest.main()
