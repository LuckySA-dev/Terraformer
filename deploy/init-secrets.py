"""Create local file secrets without printing their values.

The command is deliberately idempotent: valid existing files are retained and
never rotated implicitly. Delete a secret only as part of an intentional data
reset; losing master.key makes encrypted data unrecoverable.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
from pathlib import Path
import secrets
import sys


MASTER_KEY_BYTES = 32
POSTGRES_PASSWORD_BYTES = 32


def _write_new_secret(path: Path, value: str) -> bool:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False

    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="") as stream:
            stream.write(value)
        if os.name != "nt":
            path.chmod(0o600)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return True


def _read_ascii(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def _validate_master_key(path: Path) -> None:
    encoded = _read_ascii(path)
    try:
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"{path} is not URL-safe base64") from exc
    if len(decoded) != MASTER_KEY_BYTES:
        raise ValueError(f"{path} must decode to exactly {MASTER_KEY_BYTES} bytes")


def _validate_postgres_password(path: Path) -> None:
    value = _read_ascii(path)
    if len(value) < 32 or any(character.isspace() for character in value):
        raise ValueError(f"{path} is empty, too short, or contains whitespace")


def _resolve_output_dir(raw_path: str | None) -> Path:
    repository_root = Path(__file__).resolve().parent.parent
    return Path(raw_path).expanduser().resolve() if raw_path else repository_root / ".secrets"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        help="secret directory (default: repository-level .secrets directory)",
    )
    args = parser.parse_args()

    output_dir = _resolve_output_dir(args.output_dir)
    master_key = output_dir / "master.key"
    postgres_password = output_dir / "postgres.password"

    master_value = base64.urlsafe_b64encode(secrets.token_bytes(MASTER_KEY_BYTES)).decode("ascii")
    postgres_value = base64.urlsafe_b64encode(
        secrets.token_bytes(POSTGRES_PASSWORD_BYTES)
    ).decode("ascii").rstrip("=")

    created_master = _write_new_secret(master_key, master_value)
    created_postgres = _write_new_secret(postgres_password, postgres_value)

    try:
        _validate_master_key(master_key)
        _validate_postgres_password(postgres_password)
    except ValueError as exc:
        print(f"Secret validation failed: {exc}", file=sys.stderr)
        return 1

    for path, created in (
        (master_key, created_master),
        (postgres_password, created_postgres),
    ):
        state = "created" if created else "retained existing"
        print(f"{state}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
