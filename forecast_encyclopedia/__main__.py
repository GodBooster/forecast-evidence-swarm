import argparse
from pathlib import Path
from .demo import load_demo, FIXTURE
from .model import load_json
from .render import export


def main():
    parser = argparse.ArgumentParser(description="Build offline synthetic encyclopedia pages")
    parser.add_argument("--out", type=Path, default=Path("artifacts/encyclopedia"))
    parser.add_argument("--input", type=Path, default=FIXTURE, help="Synthetic encyclopedia fixture input")
    parser.add_argument("--core-report", type=Path, help="Read and validate an actual core v1 report")
    parser.add_argument("--core-consent", type=Path, help="Explicit per-delivery publication grants; otherwise core claims stay private")
    args = parser.parse_args()
    if args.core_consent and not args.core_report:
        parser.error("--core-consent requires --core-report")
    records = load_demo(args.input)
    if args.core_report:
        from .adapter import adapt_report
        grants = load_json(args.core_consent.read_text()) if args.core_consent else {}
        records += adapt_report(load_json(args.core_report.read_text()), grants)
    count = export(records, args.out)
    print(f"OFFLINE / SYNTHETIC / TEMPLATE-GENERATED: {count} public HTML/JSON files")
    print(f"Index: {(args.out / 'index.html').absolute()}")
    if args.core_report:
        print("Actual supplied core report validated by deterministic replay; imported records require explicit consent to appear.")


if __name__ == "__main__":
    main()
