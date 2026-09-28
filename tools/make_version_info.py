"""Write a PyInstaller Windows version resource from version.json.

    python tools/make_version_info.py build/version_info.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041204B0', [
      StringStruct('CompanyName', 'Wireless Limitless'),
      StringStruct('FileDescription', 'Wireless Limitless - QCY earbuds controller'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'WirelessLimitless'),
      StringStruct('OriginalFilename', 'WirelessLimitless.exe'),
      StringStruct('ProductName', 'Wireless Limitless'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x0412, 1200])])
  ]
)
"""


def main() -> None:
    version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    a, b, c = (int(x) for x in version.split("."))
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.format(a=a, b=b, c=c, v=version), encoding="utf-8")
    print(version)


if __name__ == "__main__":
    main()
