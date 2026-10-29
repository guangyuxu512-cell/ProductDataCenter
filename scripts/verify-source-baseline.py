"""校验复制的中控共享文件，防止第一版悄悄改变组件、布局或主题。"""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "docs/source-baseline.json").read_text(encoding="utf-8"))
errors = []
for relative, expected in manifest["unchanged_files"].items():
    path = root / relative
    if not path.is_file():
        errors.append(relative)
        continue
    data = path.read_bytes()
    source_blob = manifest["source_git_blobs"][relative]
    git_blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if hashlib.sha256(data).hexdigest() != expected or git_blob != source_blob:
        errors.append(relative)
if errors:
    raise SystemExit("来源文件发生变化：\n" + "\n".join(errors))
print(f"中控原样复用文件校验通过：{len(manifest['unchanged_files'])} 项")
