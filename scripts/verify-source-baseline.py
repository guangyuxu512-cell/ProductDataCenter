"""校验复制的中控共享文件，防止第一版悄悄改变组件、布局或主题。"""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "docs/source-baseline.json").read_text(encoding="utf-8"))
errors = []
for relative, expected in manifest["unchanged_files"].items():
    path = root / relative
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        errors.append(relative)
if errors:
    raise SystemExit("来源文件发生变化：\n" + "\n".join(errors))
print(f"中控原样复用文件校验通过：{len(manifest['unchanged_files'])} 项")
