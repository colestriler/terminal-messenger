from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYPROJECT = ROOT / "pyproject.toml"
DIST_DIR = ROOT / "dist"
DOTENV = ROOT / ".env"
VERSION_PATTERN = re.compile(r'(?m)^(version\s*=\s*")([^"]+)(")$')


def fail(message: str) -> None:
    raise SystemExit(message)


def replace_version(pyproject_text: str, new_version: str) -> tuple[str, str]:
    match = VERSION_PATTERN.search(pyproject_text)
    if not match:
        fail("Could not find the package version in pyproject.toml.")
    current_version = match.group(2)
    if current_version == new_version:
        fail(f"Version is already {new_version}. Pick a new version before deploying.")
    updated = VERSION_PATTERN.sub(rf'\g<1>{new_version}\g<3>', pyproject_text, count=1)
    return current_version, updated


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, cwd=ROOT, env=env)


def load_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    if not DOTENV.exists():
        return values

    for raw_line in DOTENV.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def main() -> int:
    if len(sys.argv) != 2:
        fail("Usage: yarn deploy <new-version>")

    new_version = sys.argv[1].strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9._-]+)?", new_version):
        fail("Version should look like 0.1.1 or 0.2.0.")

    original_text = PYPROJECT.read_text()
    current_version, updated_text = replace_version(original_text, new_version)
    PYPROJECT.write_text(updated_text)

    try:
        shutil.rmtree(DIST_DIR, ignore_errors=True)

        run([sys.executable, "-m", "pip", "install", "--upgrade", "build", "twine"])
        run([sys.executable, "-m", "build"])

        dist_files = sorted(str(path) for path in DIST_DIR.glob("*"))
        if not dist_files:
            fail("Build succeeded but dist/ is empty.")

        run([sys.executable, "-m", "twine", "check", *dist_files])

        env = os.environ.copy()
        env.update(load_dotenv())
        token = env.get("PYPI_TOKEN")
        if token:
            env["TWINE_USERNAME"] = "__token__"
            env["TWINE_PASSWORD"] = token

        run([sys.executable, "-m", "twine", "upload", *dist_files], env=env)
    except subprocess.CalledProcessError:
        PYPROJECT.write_text(original_text)
        fail(f"Deploy failed. Restored pyproject.toml to version {current_version}.")

    print(f"Published terminal-messenger {new_version}.")
    print("Commit and tag the version bump if you want git to match PyPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
