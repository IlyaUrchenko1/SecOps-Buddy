from __future__ import annotations

import argparse
import time
from pathlib import Path

from secops_buddy.utils import find_root


def _restart_flag_path(config_path: str) -> Path:
    cfg = Path(config_path).expanduser().resolve()
    root = find_root(cfg)
    p = (root / "var" / "secops-buddy" / "restart.flag").resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def restart(config_path: str) -> int:
    p = _restart_flag_path(config_path)
    p.write_text(str(time.time()), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secops_buddy.control")
    parser.add_argument("--config", required=True)
    parser.add_argument("cmd", choices=["restart"])
    args = parser.parse_args(argv)
    if args.cmd == "restart":
        return restart(args.config)
    return 2

