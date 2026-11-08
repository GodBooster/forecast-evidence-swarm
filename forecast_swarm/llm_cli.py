"""Shared command-line wiring for `--roles scripted|llm`.

Scripted (default) needs no network and is byte-for-byte the previous behaviour.
LLM mode needs exactly one source of model text:

* `--replay CASSETTE`: offline, deterministic, free. Limits come from the cassette.
* `--live`: calls the provider named in FORECAST_LLM_* environment values. Paid.
  Requires explicit per-order and whole-run cost ceilings and integer prices, and
  refuses to start unless (orders that can reach the model) x (per-order ceiling)
  fits the run ceiling. `--record PATH` saves a sanitized cassette for replay.
"""

import json
import os
from pathlib import Path

from .evidence import canonical_bytes, validate_case, verifier
from .inference import (ConfigError, InferenceEngine, Limits, RecordingProvider, ReplayProvider,
                        format_usd, load_cassette, provider_from_env, provider_options_from_env,
                        read_env_file, usd_to_nano)

LIVE_ONLY = ("record", "env_file", "max_cost_usd", "max_run_cost_usd", "max_output_tokens", "timeout_s",
             "input_price_nano_usd_per_token", "output_price_nano_usd_per_token")
DEFAULT_MAX_OUTPUT_TOKENS = 1500
DEFAULT_TIMEOUT_S = 60


def add_arguments(parser):
    group = parser.add_argument_group("analyst role mode")
    group.add_argument("--roles", choices=("scripted", "llm"), default="scripted",
                       help="scripted (default, offline) or llm analyst inside the same gates")
    group.add_argument("--replay", type=Path, help="LLM mode: replay a recorded or hand-authored cassette offline")
    group.add_argument("--live", action="store_true",
                       help="LLM mode: call the provider configured by FORECAST_LLM_* (paid; owner approval required)")
    group.add_argument("--record", type=Path, help="with --live: write a sanitized cassette for later replay")
    group.add_argument("--env-file", type=Path, help="with --live: read FORECAST_LLM_* values from this local file")
    group.add_argument("--max-cost-usd", help="with --live: cost ceiling per order, e.g. 0.01")
    group.add_argument("--max-run-cost-usd", help="with --live: cost ceiling for the whole run, e.g. 0.05")
    group.add_argument("--max-output-tokens", type=int, help=f"with --live: per call (default {DEFAULT_MAX_OUTPUT_TOKENS})")
    group.add_argument("--timeout-s", type=int, help=f"with --live: per call (default {DEFAULT_TIMEOUT_S})")
    group.add_argument("--input-price-nano-usd-per-token", type=int,
                       help="with --live: operator-supplied price; 1000 = $1 per million tokens")
    group.add_argument("--output-price-nano-usd-per-token", type=int,
                       help="with --live: operator-supplied price; 1000 = $1 per million tokens")


def _eligible_orders(cases):
    count = 0
    for case in cases:
        validate_case(case)
        inputs = json.loads(canonical_bytes(case))
        if verifier(inputs)["status"] == "VALID":
            count += 1
    return count


class LlmSetup:
    def __init__(self, engine_factory, role_info, recorder=None, limits=None, record_path=None, options=None):
        self.engine_factory = engine_factory
        self.role_info = role_info
        self._recorder, self._limits, self._record_path = recorder, limits, record_path
        self._options = dict(options or {})

    def finish(self):
        """Write the recorded cassette (live runs with --record). Returns its path or None."""
        if self._recorder is None or self._record_path is None:
            return None
        cassette = self._recorder.cassette(
            self._limits, "Recorded from a live provider over synthetic fixture inputs. Contains model text and "
                          "token usage only; no headers, keys or account data.", None, self._options)
        path = Path(self._record_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cassette, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        return path


def setup_from_args(parser, args, cases, environ=None):
    """Return None for scripted mode, else an LlmSetup. Calls parser.error on misuse."""
    given_live_only = [name for name in LIVE_ONLY if getattr(args, name) not in (None, False)]
    if args.roles == "scripted":
        if args.replay or args.live or given_live_only:
            parser.error("--replay/--live and limit options require --roles llm")
        return None
    if bool(args.replay) == bool(args.live):
        parser.error("--roles llm needs exactly one of --replay CASSETTE or --live")
    try:
        if args.replay:
            if given_live_only:
                parser.error("replay uses the limits recorded in the cassette; limit options apply to --live only")
            cassette, digest = load_cassette(args.replay)
            limits = Limits.from_record(cassette["limits"])
            provider = ReplayProvider(cassette)

            def factory():
                return InferenceEngine(provider, limits, cassette["temperature_milli"], cassette["options"])

            info = {"analyst": "llm", "critic": "scripted", "verifier": "scripted",
                    "provider": cassette["provider"], "model": cassette["model"], "inference_source": "REPLAY",
                    "cassette": {"file": Path(args.replay).name, "sha256": digest, "origin": cassette["origin"]},
                    "run_cost_cap_nano_usd": None}
            return LlmSetup(factory, info)

        env = dict(os.environ if environ is None else environ)
        if args.env_file:
            env.update(read_env_file(args.env_file))
        if args.max_cost_usd is None or args.max_run_cost_usd is None:
            parser.error("--live requires --max-cost-usd (per order) and --max-run-cost-usd")
        input_price = args.input_price_nano_usd_per_token
        output_price = args.output_price_nano_usd_per_token
        if input_price is None and env.get("FORECAST_LLM_INPUT_NANO_USD_PER_TOKEN"):
            input_price = int(env["FORECAST_LLM_INPUT_NANO_USD_PER_TOKEN"])
        if output_price is None and env.get("FORECAST_LLM_OUTPUT_NANO_USD_PER_TOKEN"):
            output_price = int(env["FORECAST_LLM_OUTPUT_NANO_USD_PER_TOKEN"])
        if input_price is None or output_price is None:
            parser.error("--live requires input and output prices (flags or FORECAST_LLM_*_NANO_USD_PER_TOKEN)")
        limits = Limits(max_calls=1,
                        max_output_tokens=args.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
                        timeout_s=args.timeout_s or DEFAULT_TIMEOUT_S,
                        max_cost_nano_usd=usd_to_nano(args.max_cost_usd),
                        input_price_nano_usd_per_token=input_price,
                        output_price_nano_usd_per_token=output_price)
        run_cap = usd_to_nano(args.max_run_cost_usd)
        eligible = _eligible_orders(cases)
        if eligible * limits.max_cost_nano_usd > run_cap:
            parser.error(f"{eligible} orders x {format_usd(limits.max_cost_nano_usd)} per order exceeds the run "
                         f"ceiling {format_usd(run_cap)}; lower --max-cost-usd or raise --max-run-cost-usd")
        live = provider_from_env(env)
        options = provider_options_from_env(env, live.kind)
        recorder = RecordingProvider(live)

        def factory():
            return InferenceEngine(recorder, limits, None, options)

        info = {"analyst": "llm", "critic": "scripted", "verifier": "scripted",
                "provider": live.kind, "model": live.model, "inference_source": "LIVE", "cassette": None,
                "run_cost_cap_nano_usd": run_cap}
        return LlmSetup(factory, info, recorder, limits, args.record, options)
    except (ConfigError, ValueError, OSError) as error:
        parser.error(str(error))
