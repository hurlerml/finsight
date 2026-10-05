import json
import re
from pathlib import Path

from app.version import product_version

ROOT = Path(__file__).resolve().parents[2]


def _gateway_version() -> str:
    pom = (ROOT / "fints-gateway" / "pom.xml").read_text(encoding="utf-8")
    match = re.search(
        r"<artifactId>fints-gateway</artifactId>\s*<version>([^<]+)</version>",
        pom,
    )
    assert match is not None
    return match.group(1)


def test_product_version_is_loaded_from_version_json() -> None:
    declared = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    assert product_version() == declared["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", declared["version"])


def test_package_and_gateway_versions_match_the_product() -> None:
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == product_version()
    assert _gateway_version() == product_version()
