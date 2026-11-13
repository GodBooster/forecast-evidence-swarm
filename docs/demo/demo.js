// Forecast Evidence Swarm demo page. Plain browser JavaScript, no network calls beyond the
// three JSON files next to this page. The hash rule mirrors forecast_swarm/evidence.py:
//   SHA-256( UTF-8("forecast-evidence-swarm/v1:bundle\n") + canonical_json(bundle.content) )
// canonical_json = keys sorted recursively, no whitespace, array order kept, integers only.
"use strict";

const SCHEMA_PREFIX = "forecast-evidence-swarm/v1:";

function canonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("Canonical v1 accepts only integers");
    return String(value);
  }
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (typeof value === "object") {
    return "{" + Object.keys(value).sort().map((k) => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
  }
  throw new Error("Unsupported value in canonical JSON");
}

async function commitment(domain, value) {
  if (!(globalThis.crypto && crypto.subtle && crypto.subtle.digest)) throw new Error("Web Crypto unavailable");
  const bytes = new TextEncoder().encode(SCHEMA_PREFIX + domain + "\n" + canonical(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// MATCH / MISMATCH / UNAVAILABLE. A missing or malformed reference is never a match.
function compare(expected, computed) {
  const hex = /^[0-9a-f]{64}$/;
  if (typeof expected !== "string" || !hex.test(expected) || typeof computed !== "string" || !hex.test(computed)) {
    return "UNAVAILABLE";
  }
  return expected === computed ? "MATCH" : "MISMATCH";
}

const short = (h) => (h ? h.slice(0, 8) + "…" + h.slice(-6) : "—");
const yocto = (s) => {
  const v = BigInt(s), unit = 10n ** 24n, whole = v / unit, frac = (v % unit).toString().padStart(24, "0").replace(/0+$/, "");
  return whole.toString() + (frac ? "." + frac : "");
};

function setHash(name, full) {
  const el = document.querySelector(`[data-hash="${name}"]`);
  if (!el) return;
  el.dataset.full = full || "";
  el.textContent = full ? (el.getAttribute("aria-expanded") === "true" ? full : short(full)) : "—";
}

function wireHashToggles() {
  document.querySelectorAll("[data-hash]").forEach((el) => {
    el.addEventListener("click", () => {
      const open = el.getAttribute("aria-expanded") !== "true";
      el.setAttribute("aria-expanded", String(open));
      el.textContent = el.dataset.full ? (open ? el.dataset.full : short(el.dataset.full)) : "—";
    });
  });
}

const state = { original: null, reference: null, changed: false };

function currentContent() {
  const content = structuredClone(state.original.content);
  if (state.changed) content.inputs.evidence[0].yes_count = 16;
  return content;
}

async function runCheck() {
  const which = document.getElementById("which");
  const result = document.getElementById("result");
  const ev = currentContent().inputs.evidence[0];
  which.textContent = (state.changed ? "Changed copy" : "Original delivery") + ` · ${ev.yes_count} of ${ev.sample_count} YES`;
  let computed = null;
  try {
    computed = await commitment("bundle", currentContent());
  } catch (err) {
    computed = null;
  }
  setHash("computed", computed);
  const verdict = compare(state.reference, computed);
  result.className = "result " + (verdict === "MATCH" ? "ok" : "bad");
  result.textContent = verdict === "MATCH" ? "✓ Matches accepted delivery"
    : verdict === "MISMATCH" ? "✗ " + (state.changed ? "Changed copy · " : "") + "Hash mismatch"
    : "! Verification unavailable";
  document.getElementById("change").disabled = state.changed;
  document.getElementById("restore").disabled = !state.changed;
  return verdict;
}

function unavailable(message) {
  const result = document.getElementById("result");
  result.className = "result bad";
  result.textContent = "! Verification unavailable" + (message ? " · " + message : "");
  document.getElementById("change").disabled = true;
  document.getElementById("restore").disabled = true;
}

async function load(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(path + ": HTTP " + response.status);
  return response.json();
}

async function main() {
  wireHashToggles();
  let forecast, receipt, delivery;
  try {
    [forecast, receipt, delivery] = await Promise.all([
      load("data/forecast.json"), load("data/receipt.json"), load("data/delivery-job0.json"),
    ]);
  } catch (err) {
    unavailable("demo data could not be loaded");
    return;
  }
  const f = (k) => document.querySelector(`[data-f="${k}"]`);
  f("question").textContent = forecast.question;
  f("evidence").textContent = `${forecast.yes_count} YES / ${forecast.sample_count} observations · source ${forecast.evidence_id}`;
  f("probability").textContent = (forecast.probability_bps / 100).toFixed(2) + "% YES";
  f("interval").textContent = `${forecast.interval_bps[0] / 100}–${forecast.interval_bps[1] / 100}%`;
  f("method").textContent = forecast.method;
  f("outcome").textContent = forecast.outcome;
  f("provenance").textContent = `Live run on ${forecast.run_date}, model ${forecast.model} via ${forecast.provider}; ` +
    `recorded in docs/VALIDATION.md. A separate run from the paid NEAR job.`;

  const r = (k) => document.querySelector(`[data-r="${k}"]`);
  r("reward").textContent = yocto(receipt.reward_yocto) + " testnet NEAR";
  r("status").textContent = receipt.status;
  r("consent").textContent = receipt.publication_consent ? "✓ granted on chain" : "✗ not granted";
  r("snapshot").textContent = `Recorded snapshot of ${receipt.contract_id}, block ${receipt.snapshot.block_height}, ` +
    `${receipt.snapshot.captured_at.replace("T", " ").replace("Z", " UTC")}.`;
  r("accept-link").href = receipt.accept_explorer;
  setHash("accepted", receipt.artifact_sha256);

  state.original = delivery;
  state.reference = receipt.artifact_sha256;
  document.getElementById("change").addEventListener("click", () => { state.changed = true; runCheck(); });
  document.getElementById("restore").addEventListener("click", () => { state.changed = false; runCheck(); });
  await runCheck();
}

window.FES = { canonical, commitment, compare };
if (typeof document !== "undefined") main();
