from __future__ import annotations
import argparse, asyncio, json
from pathlib import Path
import yaml
from bullet_in.adapters.factory import build_adapters
from bullet_in.metrics import benchmark


def main() -> None:
    ap = argparse.ArgumentParser(
        description="SLO-1 순차 vs 병렬 fetch 벤치마크 (DB 미적재, JSON stdout)")
    ap.add_argument("--gap", type=float, default=60.0,
                    help="순차 · 병렬 패스 사이 대기 초 (기본 60)")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    adapters = build_adapters(cfg)
    result = asyncio.run(benchmark(adapters, gap_sec=args.gap))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
