"""
진입점. --config로 설정 파일 경로를 지정할 수 있어 서버마다 다른 설정 사용 가능.
"""

import argparse
import logging
import sys

from src.pipeline import Pipeline


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="NGINX API Discovery Pipeline")
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="설정 파일 경로 (기본값: config/settings.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Inventory(데이터)만 갱신하고 Feature/딥러닝 학습은 건너뛴다",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    try:
        pipeline = Pipeline(config_path=args.config)
        result = pipeline.run(inventory_only=args.inventory_only)
        sys.exit(0)
    except FileNotFoundError as e:
        logging.error(str(e))
        sys.exit(1)
    except Exception as e:
        logging.exception(f"Pipeline 오류: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
