import copy
import json
import tempfile
import contextlib
import io
import runpy
from unittest.mock import patch
import unittest
from html.parser import HTMLParser
from pathlib import Path

from forecast_encyclopedia.demo import load_demo
from forecast_encyclopedia.model import (accuracy, append_version, canonical, digest, new_claim,
    revise_claim, validate_record, verify_extension, safe_url, load_json)
from forecast_encyclopedia.render import build_files, export, MANIFEST
from forecast_encyclopedia.adapter import adapt_report


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.scripts = [], set(), []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a":
            self.links.append(a.get("href", ""))
        if tag == "script" or any(k.startswith("on") for k in a):
            self.scripts.append(tag)


class EncyclopediaTests(unittest.TestCase):
    def setUp(self):
        self.future, self.wrong, self.disputed = load_demo()

    def fresh(self, transform):
        r = self.future
        s, i = copy.deepcopy(r["versions"][0]["snapshot"]), copy.deepcopy(r["identity"])
        transform(s, i)
        return new_claim(i, s, r["publication"])

    def test_previous_version_and_forecast_preserved(self):
        first, second = self.wrong["versions"]
        self.assertEqual(first["forecast_sha256"], second["forecast_sha256"])
        self.assertEqual(first["sha256"], second["previous_sha256"])
        self.assertEqual(first["snapshot"]["outcome"]["status"], "UNRESOLVED")
        one = copy.deepcopy(self.wrong); one["versions"] = one["versions"][:1]
        frozen = canonical(one)
        self.assertEqual(append_version(one, second["snapshot"]), self.wrong)
        self.assertEqual(canonical(one), frozen)
        self.assertEqual(verify_extension(one, self.wrong), self.wrong)

    def test_revision_of_each_identity_field_creates_new_claim(self):
        for key in self.future["identity"]:
            with self.subTest(key=key):
                i = copy.deepcopy(self.future["identity"])
                i[key] = "2026-11-11T12:00:00Z" if key == "resolution_at" else i[key] + " revised"
                revised = revise_claim(self.future, i, self.future["versions"][0]["snapshot"])
                self.assertNotEqual(revised["id"], self.future["id"])
                self.assertEqual(revised["previous_claim"], self.future["id"])
                self.assertNotIn("publication", revised)
                forged = copy.deepcopy(self.future); forged["identity"] = i
                with self.assertRaises(ValueError): validate_record(forged)
        with self.assertRaises(ValueError):
            revise_claim(self.future, self.future["identity"], self.future["versions"][0]["snapshot"])

    def test_cutoff_boundary_and_post_cutoff_rejection(self):
        validate_record(self.future)  # availability exactly at cutoff is allowed
        def later(s, i):
            s["as_of"] = "2026-11-06T10:00:01Z"
            s["evidence"][0]["available_at"] = s["as_of"]
        with self.assertRaisesRegex(ValueError, "Post-cutoff"): self.fresh(later)
        def unavailable(s, i): s["evidence"][0]["available_at"] = "2026-11-06T10:00:01Z"
        with self.assertRaises(ValueError): self.fresh(unavailable)

    def test_new_version_cannot_rewrite_forecast_or_evidence(self):
        for mode in ("probability", "evidence", "cutoff", "validity"):
            s = copy.deepcopy(self.future["versions"][0]["snapshot"])
            s["as_of"] = "2026-11-07T10:00:00Z"
            if mode == "probability": s["forecast"]["probability_bps"] = 9900
            if mode == "evidence": s["evidence"][0]["excerpt"] = "Rewritten history"
            if mode == "cutoff": s["forecast"]["cutoff"] = s["as_of"]
            if mode == "validity": s["delivery_validity"] = "INVALID"
            with self.subTest(mode=mode), self.assertRaises(ValueError): append_version(self.future, s)

    def test_strictly_increasing_version_times(self):
        s = copy.deepcopy(self.future["versions"][0]["snapshot"])
        with self.assertRaises(ValueError): append_version(self.future, s)
        s["as_of"] = "2026-11-05T10:00:00Z"
        with self.assertRaises(ValueError): append_version(self.future, s)

    def test_wrong_but_valid_and_accepted(self):
        s = self.wrong["versions"][-1]["snapshot"]
        self.assertEqual((s["delivery_validity"], s["customer_acceptance"]), ("VALID", "ACCEPTED"))
        self.assertEqual(accuracy(s), {"status":"EVALUATED", "direction_correct":False, "brier_scaled_1e8":56250000})

    def test_unresolved_proposed_disputed_are_not_scored(self):
        self.assertEqual(accuracy(self.future["versions"][0]["snapshot"])["status"], "NOT_EVALUABLE")
        self.assertEqual(accuracy(self.disputed["versions"][0]["snapshot"])["status"], "NOT_EVALUABLE")
        for state in ("PROPOSED", "DISPUTED"):
            s = copy.deepcopy(self.wrong["versions"][-1]["snapshot"])
            s["outcome"]["status"] = state
            r = new_claim(self.wrong["identity"], s)
            self.assertIsNone(accuracy(r["versions"][0]["snapshot"])["direction_correct"])

    def test_finality_requires_source_time_value_and_cannot_reverse(self):
        for field, value in (("value", None), ("resolved_at", None), ("resolved_at", "2026-11-01T12:00:00Z")):
            s = copy.deepcopy(self.wrong["versions"][-1]["snapshot"]); s["outcome"][field] = value
            with self.assertRaises(ValueError): new_claim(self.wrong["identity"], s)
        s = copy.deepcopy(self.wrong["versions"][-1]["snapshot"])
        next(e for e in s["evidence"] if e["id"] == "resolution")["source"] = "other-source"
        with self.assertRaises(ValueError): new_claim(self.wrong["identity"], s)
        s = copy.deepcopy(self.wrong["versions"][-1]["snapshot"]); s["as_of"] = "2026-11-04T10:00:00Z"; s["outcome"]["status"] = "DISPUTED"
        with self.assertRaises(ValueError): append_version(self.wrong, s)

    def test_unknown_is_not_no_and_no_consensus_rule(self):
        def negative(s, i): s["outcome"]["value"] = 0
        with self.assertRaises(ValueError): self.fresh(negative)
        def consensus(s, i): s["outcome"]["status"] = "CONSENSUS_FINAL"
        with self.assertRaises(ValueError): self.fresh(consensus)

    def test_private_default_explicit_consent_and_revocation(self):
        private = copy.deepcopy(self.future); private.pop("publication")
        self.assertEqual(set(build_files([private])), {"index.html", "index.json"})
        private["publication"] = {"allowed": True, "consent": None}
        with self.assertRaises(ValueError): build_files([private])
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as d:
            export([self.future], d)
            private["publication"] = {"allowed": False, "consent": None}
            export([private], d)
            all_bytes = b"".join(p.read_bytes() for p in Path(d).iterdir())
            self.assertNotIn(self.future["id"].encode(), all_bytes)
            self.assertNotIn(self.future["identity"]["question"].encode(), all_bytes)
            self.assertEqual({p.name for p in Path(d).iterdir()}, {"index.html", "index.json", MANIFEST})
            validate_record(private)  # local audit remains intact

    def test_public_reference_to_private_is_omitted_everywhere(self):
        private = copy.deepcopy(self.future); private.pop("publication")
        i = copy.deepcopy(private["identity"]); i["question"] = "A public revised question?"
        public = revise_claim(private, i, private["versions"][0]["snapshot"], self.future["publication"])
        data = "".join(build_files([private, public]).values())
        self.assertNotIn(private["id"], data)
        self.assertNotIn(private["identity"]["question"], data)
        self.assertNotIn("synthetic demo owner", data)

    def test_hostile_html_is_escaped_and_links_are_safe(self):
        attack = '<script>alert(1)</script><img src=x onerror="alert(1)">'
        def hostile(s, i):
            i["question"] = attack
            s["evidence"][0]["excerpt"] = attack
            s["criticism"] = [attack]
            s["statements"][0]["text"] = attack
        r = self.fresh(hostile)
        for name, body in build_files([r]).items():
            if name.endswith(".html"):
                parser = LinkParser(); parser.feed(body)
                self.assertFalse(parser.scripts)
                self.assertNotIn("<script>", body)
                self.assertIn("&lt;script&gt;", body)
        for url in ("javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "//evil.test", "https://u:p@example.com", "https://example.com\n/x", "https:\\evil.test", "https://[", "https://example.com:bad"):
            with self.subTest(url=url), self.assertRaises(ValueError): safe_url(url)
        safe_url("https://example.com/reference?a=1&b=2")

    def test_unsafe_ids_and_synthetic_urls_rejected(self):
        for value in ("../escape", "/tmp/x", "x\" onclick=\"bad", "..", "a/b"):
            def bad(s, i): s["evidence"][0]["id"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): self.fresh(bad)
        def link(s, i): s["evidence"][0]["url"] = "https://example.com"
        with self.assertRaises(ValueError): self.fresh(link)
        r = copy.deepcopy(self.future); r["id"] = "../../x"
        with self.assertRaises(ValueError): build_files([r])

    def test_output_foreign_files_symlinks_and_manifest_paths_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as d:
            root = Path(d); target = root / "target"; target.mkdir(); (target / "keep").write_text("KEEP")
            link = root / "link"; link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError): export([], link / "child")
            with self.assertRaises(ValueError): export([], target)
            out = root / "out"; export([self.future], out)
            (out / "intruder").symlink_to(target / "keep")
            with self.assertRaises(ValueError): export([], out)
            (out / "intruder").unlink(); (out / MANIFEST).write_text('["../target/keep"]')
            with self.assertRaises(ValueError): export([], out)
            self.assertEqual((target / "keep").read_text(), "KEEP")

    def test_tampering_chain_and_truncation(self):
        r = copy.deepcopy(self.wrong); r["versions"][0]["snapshot"]["criticism"][0] = "tampered"
        with self.assertRaises(ValueError): validate_record(r)
        r = copy.deepcopy(self.wrong); r["versions"][1]["previous_sha256"] = "0" * 64
        with self.assertRaises(ValueError): validate_record(r)
        r = copy.deepcopy(self.wrong); r["versions"] = r["versions"][:1]
        with self.assertRaises(ValueError): verify_extension(self.wrong, r)
        # A fully rehashed alternative is detectable only against a trusted local history.
        s = copy.deepcopy(self.wrong["versions"][0]["snapshot"]); s["criticism"][0] = "rewritten"
        rehashed = new_claim(self.wrong["identity"], s)
        with self.assertRaises(ValueError): verify_extension(self.wrong, rehashed)

    def test_strict_types_references_and_unknown_fields(self):
        for p in (True, 0.7, -1, 10001):
            def bad(s, i): s["forecast"]["probability_bps"] = p
            with self.assertRaises(ValueError): self.fresh(bad)
        def missing(s, i): s["statements"][0]["evidence_ids"] = ["absent"]
        with self.assertRaises(ValueError): self.fresh(missing)
        def uncited(s, i): s["statements"][0]["evidence_ids"] = []
        with self.assertRaises(ValueError): self.fresh(uncited)
        r = copy.deepcopy(self.future); r["secret_extra"] = "unexpected"
        with self.assertRaises(ValueError): validate_record(r)
        with self.assertRaises(ValueError): canonical(float("nan"))
        self.assertNotEqual(digest("forecast", {}), digest("version", {}))

    def test_reproducibility_and_all_local_links(self):
        files = build_files(load_demo())
        self.assertEqual(files, build_files(list(reversed(load_demo()))))
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as a, tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as b:
            export(load_demo(), a); export(load_demo(), b)
            self.assertEqual({p.name:p.read_bytes() for p in Path(a).iterdir()}, {p.name:p.read_bytes() for p in Path(b).iterdir()})
            export(load_demo(), a)
            self.assertEqual({p.name:p.read_bytes() for p in Path(a).iterdir()}, {p.name:p.read_bytes() for p in Path(b).iterdir()})
        for name, body in files.items():
            if not name.endswith(".html"): continue
            parser = LinkParser(); parser.feed(body)
            for link in parser.links:
                if link.startswith("#"): self.assertIn(link[1:], parser.ids)
                else: self.assertIn(link, files)



    def test_cli_replays_offline_without_network(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as d:
            outputs = []
            for name in ("first", "replay"):
                out = Path(d) / name
                with patch("socket.socket", side_effect=AssertionError("Network forbidden")), patch("socket.create_connection", side_effect=AssertionError("Network forbidden")), patch("sys.argv", ["forecast_encyclopedia", "--out", str(out)]), contextlib.redirect_stdout(io.StringIO()):
                    runpy.run_module("forecast_encyclopedia", run_name="__main__")
                outputs.append({p.name:p.read_bytes() for p in out.iterdir()})
            self.assertEqual(outputs[0], outputs[1])

    def test_ambiguous_json_and_canonical_bytes(self):
        for text in ('{"allowed":false,"allowed":true}', '{"p":NaN}', '{"p":1.0}', '{"p":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError): load_json(text)
        self.assertEqual(canonical({"z":1,"a":"é"}), b'{"a":"\xc3\xa9","z":1}')
        with self.assertRaises(ValueError): adapt_report(CoreAdapterTests().report(), [])

    def test_public_revision_link_and_safe_external_link(self):
        i = copy.deepcopy(self.future["identity"]); i["question"] = "Revised scope?"
        revised = revise_claim(self.future, i, self.future["versions"][0]["snapshot"], self.future["publication"])
        files = build_files([self.future, revised])
        self.assertIn(self.future["id"] + '.html', files[revised["id"] + '.html'])
        def link(s, i):
            s["evidence"][0].update(source="Synthetic excerpt used only in a link-escaping test", url="https://example.com/reference?a=1&b=2")
        linked = self.fresh(link)
        page = build_files([linked])[linked["id"] + '.html']
        self.assertIn('href="https://example.com/reference?a=1&amp;b=2"', page)


class CoreAdapterTests(unittest.TestCase):
    def report(self):
        from forecast_swarm.demo import run_demo
        return run_demo()

    def test_actual_core_generator_and_private_default(self):
        report = self.report()
        before = canonical(report)
        records = adapt_report(report)
        self.assertEqual(len(records), 5)
        self.assertEqual(set(build_files(records)), {"index.html", "index.json"})
        self.assertEqual(canonical(report), before)
        zero = next(r for r in records if "synthetic-05" in r["identity"]["scope"])
        self.assertEqual(zero["versions"][0]["snapshot"]["forecast"]["probability_bps"], 0)
        self.assertTrue(accuracy(zero["versions"][-1]["snapshot"])["direction_correct"])
        valid_wrong = next(r for r in records if "synthetic-01" in r["identity"]["scope"])
        self.assertFalse(accuracy(valid_wrong["versions"][-1]["snapshot"])["direction_correct"])
        invalid = next(r for r in records if "synthetic-02" in r["identity"]["scope"])
        self.assertIsNone(invalid["versions"][0]["snapshot"]["forecast"]["probability_bps"])
        self.assertEqual(invalid["versions"][0]["snapshot"]["delivery_validity"], "INVALID")

    def test_explicit_grant_is_delivery_bound(self):
        report = self.report(); grant = load_demo()[0]["publication"]
        records = adapt_report(report, {report["scenarios"][0]["delivery"]["sha256"]:grant})
        self.assertEqual(len(json.loads(build_files(records)["index.json"])["claims"]), 1)
        with self.assertRaises(ValueError): adapt_report(report, {"f"*64:grant})

    def test_core_tampering_and_forged_role_rehash_rejected(self):
        from forecast_swarm.evidence import commitment
        for mode in ("hash", "role", "quality", "acceptance", "wrapper", "schema"):
            r = self.report(); row = r["scenarios"][0]
            if mode == "hash": row["delivery"]["sha256"] = "0"*64
            if mode == "role":
                row["delivery"]["content"]["roles"]["analyst"]["probability_bps"] = 9000
                row["delivery"]["sha256"] = commitment("bundle", row["delivery"]["content"])
            if mode == "quality": row["evaluation"]["forecast_quality"]["direction_correct"] = True
            if mode == "acceptance": row["customer_acceptance"]["status"] = "REFUNDED"
            if mode == "wrapper": row["title"] = "substitution"
            if mode == "schema": r["schema_version"] = "future/v9"
            with self.subTest(mode=mode), self.assertRaises(ValueError): adapt_report(r)


if __name__ == "__main__":
    unittest.main()
