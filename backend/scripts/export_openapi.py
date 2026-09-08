from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Contract generation is deliberately environment-independent and never opens this inert URL.
os.environ.setdefault("DATABASE_URL", "postgresql://openapi:openapi@127.0.0.1:1/openapi")
os.environ.setdefault("PUBLIC_ORIGIN", "http://localhost:5173")
os.environ.setdefault("CANONICAL_NOTICE_VERSION", "openapi")
os.environ.setdefault("CANONICAL_NOTICE_TEXT", "OpenAPI generation notice")
os.environ.setdefault("SMTP_HOST", "127.0.0.1")
os.environ.setdefault("SMTP_PORT", "1")
os.environ.setdefault("SMTP_SENDER", "openapi@example.invalid")
os.environ.setdefault("RECIPIENT_ALLOW_LIST", "openapi@example.invalid")

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "openapi.json"


def canonical_openapi() -> str:
    from real_estate_crm.app import app

    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"


def export_openapi(output: Path = DEFAULT_OUTPUT, *, check: bool = False) -> bool:
    rendered = canonical_openapi()
    if check:
        return output.is_file() and output.read_text(encoding="utf-8") == rendered
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    temporary.replace(output)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the canonical public OpenAPI contract.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if the committed contract differs.")
    arguments = parser.parse_args(argv)
    return 0 if export_openapi(arguments.output.resolve(), check=arguments.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
