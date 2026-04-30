"""Generate or check the committed number-trust oracle vocabulary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.number_trust_vocabulary import build_oracle_vocabulary  # noqa: E402


DEFAULT_OUTPUT = ROOT / "docs" / "audits" / "number-trust" / "oracle-vocabulary.json"


def render_vocabulary() -> str:
    return json.dumps(build_oracle_vocabulary(), indent=2) + "\n"


def write_vocabulary(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_vocabulary(), encoding="utf-8")


def check_vocabulary(path: Path) -> bool:
    expected = render_vocabulary()
    try:
        actual = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return actual == expected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or check docs/audits/number-trust/oracle-vocabulary.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Vocabulary output path. Defaults to the committed audit artifact.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero if the output path differs from generated content.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output
    if not output.is_absolute():
        output = ROOT / output

    if args.check:
        if check_vocabulary(output):
            print(f"Vocabulary is up to date: {output}")
            return 0
        print(f"Vocabulary is out of date: {output}", file=sys.stderr)
        print(
            "Run python scripts\\generate_number_trust_oracle_vocabulary.py "
            f"--output {output}",
            file=sys.stderr,
        )
        return 1

    write_vocabulary(output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
