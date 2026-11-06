"""路径、.env 和 config.toml 的统一入口。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
ROOT = PIPELINE_DIR.parent


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    data: Path = ROOT / "data"
    raw: Path = ROOT / "data" / "raw"
    cache: Path = ROOT / "data" / "cache"
    build: Path = ROOT / "data" / "build"
    llm: Path = ROOT / "data" / "llm"
    reports: Path = ROOT / "reports"

    @property
    def hn_raw(self) -> Path:          # HF 月度 parquet（只含需要的列）
        return self.raw / "hn" / "hf"

    @property
    def hn_delta(self) -> Path:        # Algolia 增量，转成同一 schema
        return self.raw / "hn" / "delta"

    @property
    def hn_db(self) -> Path:           # 本地 DuckDB（视图 + 派生表）
        return self.data / "hn.duckdb"

    @property
    def probe(self) -> Path:           # 探针中间结果
        return self.build / "probe"


PATHS = Paths()


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """极简 .env 读取：KEY=VALUE，# 注释；不覆盖已存在的环境变量。"""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


@cache
def cfg() -> dict:
    """pipeline/config.toml。环境变量 HS_CONFIG 指向另一个 TOML 时，按键覆盖在上面（demo/config.toml 用它只拉一个月、把月份门槛降到 1）。"""
    load_dotenv()
    with open(PIPELINE_DIR / "config.toml", "rb") as f:
        base = tomllib.load(f)
    extra = os.environ.get("HS_CONFIG")
    if extra:
        p = Path(extra)
        p = p if p.is_absolute() or p.exists() else ROOT / p
        with open(p, "rb") as f:
            _merge(base, tomllib.load(f))
    return base


def _merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def env(key: str, default: str = "") -> str:
    load_dotenv()
    return os.environ.get(key, default)
