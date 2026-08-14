"""
대시보드 서버 진입점.
python3 serve.py --output ./output --port 8080
"""

import argparse
import logging

import uvicorn
import yaml

from src.dashboard.app import app, init_reader, init_config


def main():
    parser = argparse.ArgumentParser(description="API Discovery Dashboard")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--output", default=None, help="output 디렉토리 (미지정 시 config에서 읽음)")
    parser.add_argument("--reload", action="store_true", help="개발 모드 자동 재시작")
    args = parser.parse_args()

    output_dir = args.output
    if not output_dir:
        with open(args.config) as f:
            cfg = yaml.safe_load(f)
        output_dir = cfg["pipeline"]["output_dir"]

    init_reader(output_dir)
    init_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.info(f"Dashboard: http://{args.host}:{args.port}  (output: {output_dir})")
    uvicorn.run("src.dashboard.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
