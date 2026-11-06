import argparse
from pathlib import Path
from .demo import load_demo, FIXTURE
from .model import load_json
from .render import export


def main():
    parser = argparse.ArgumentParser(description="Build offline synthetic encyclopedia pages")
    parser.add_argument("--out", type=Path, default=Path("artifacts/encyclopedia"))
    parser.add_argument("--input", type=Path, default=FIXTURE, help="Synthetic encyclopedia fixture input")
    core = parser.add_mutually_exclusive_group()
    core.add_argument("--core-report", type=Path, help="Read and validate an actual core v1 report")
    core.add_argument("--core-demo", action="store_true", help="Run the actual offline core generator in memory, then validate and import its report")
    parser.add_argument("--core-consent", type=Path, help="Explicit per-delivery publication grants; otherwise core claims stay private")
    args = parser.parse_args()
    if args.core_consent and not (args.core_report or args.core_demo):
        parser.error("--core-consent requires --core-report or --core-demo")
    records = load_demo(args.input)
    if args.core_report or args.core_demo:
        from .adapter import adapt_report
        grants = load_json(args.core_consent.read_text()) if args.core_consent else {}
        if args.core_demo:
            from forecast_swarm.demo import run_demo
            report = run_demo()
        else:
            report = load_json(args.core_report.read_text())
        records += adapt_report(report, grants)
    count = export(records, args.out)
    print(f"OFFLINE / SYNTHETIC / TEMPLATE-GENERATED: {count} public HTML/JSON files")
    print(f"Index: {(args.out / 'index.html').absolute()}")
    if args.core_report or args.core_demo:
        print("Actual supplied core report validated by deterministic replay; imported records require explicit consent to appear.")


if __name__ == "__main__":
    main()
