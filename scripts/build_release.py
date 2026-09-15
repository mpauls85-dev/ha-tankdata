"""Package only the integration and public documentation."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

root = Path(__file__).resolve().parents[1]
component = root / "custom_components" / "ha_tankdata"
version = json.loads((component / "manifest.json").read_text())["version"]
destination = root / "dist"
destination.mkdir(exist_ok=True)
archive = destination / f"ha-tankdata-{version}.zip"
files = [
    p
    for p in component.rglob("*")
    if p.is_file() and p.suffix in {".py", ".json", ".yaml", ".js", ".png", ".svg"}
]
files += [root / "README.md"]
files += [root / "hacs.json"]
with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
    for path in sorted(files):
        info = ZipInfo(path.relative_to(root).as_posix())
        info.compress_type = ZIP_DEFLATED
        output.writestr(info, path.read_bytes())
with ZipFile(archive) as output:
    assert output.testzip() is None
    assert all(
        not n.startswith(("resources/", ".local/", ".venv/")) for n in output.namelist()
    )
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(destination / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
print(f"Created {archive.name}: {len(files)} files, SHA256 {digest}")
