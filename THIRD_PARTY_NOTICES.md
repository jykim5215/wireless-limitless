# Third-party notices

Wireless Limitless bundles or builds on the following components.

| Component | Version | License | Use |
|---|---|---|---|
| Python runtime | 3.14 | PSF-2.0 | Interpreter embedded by PyInstaller |
| [bleak](https://github.com/hbldh/bleak) | 3.0.2 | MIT | Bluetooth LE (WinRT backend) |
| [pywinrt](https://github.com/pywinrt/pywinrt) (`winrt-*`) | 3.2.1 | MIT | Windows Runtime bindings used by bleak |
| [pywebview](https://github.com/r0x0r/pywebview) | 6.2.1 | BSD-3-Clause | Native window hosting the WebView2 UI |
| [pythonnet](https://github.com/pythonnet/pythonnet) / clr_loader | 3.1.0 / 0.3.1 | MIT | .NET bridge used by pywebview |
| cffi / pycparser | 2.1.1 / 3.0 | MIT-0 / BSD-3-Clause | Dependencies of clr_loader |
| bottle / proxy_tools / typing_extensions | 0.13.4 / 0.1.0 / 4.16.0 | MIT / MIT / PSF-2.0 | pywebview dependencies (the bottle HTTP server is never started) |
| [PyInstaller](https://pyinstaller.org) bootloader | 6.22.3 | GPL-2.0-or-later with bootloader exception | Executable packaging (the exception allows distributing the bundle under any terms) |
| NanumSquareRound (나눔스퀘어라운드) | 1.000 | SIL OFL 1.1 — see `licenses/OFL-1.1-NanumSquareRound.txt` | UI font (R / B / EB woff2) |
| QCY HT08 EQ preset tables (from [qcyx](https://github.com/allansomensi/qcyx)) | — | MIT — see `licenses/MIT-qcyx.txt` | Data in `catalog.py` |

Protocol knowledge was cross-checked against public write-ups by
[hui1601/Quicky](https://github.com/hui1601/Quicky) (no license; only facts about
the wire protocol were used, no code) and verified against real hardware.

Microsoft Edge WebView2 Runtime is part of Windows 11 and is not redistributed.

"QCY" and "MeloBuds" are trademarks of their owner. Wireless Limitless is an
unofficial project, not affiliated with or endorsed by QCY.
