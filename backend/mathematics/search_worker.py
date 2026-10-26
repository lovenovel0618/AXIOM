"""SEARCH 固定子程序入口：只跑指定 registry 家族，不載入使用者程式。"""
import json
from pathlib import Path
import sys


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ingestion.worker import configure
    from mathematics.search import search, STRATEGIES
    from mathematics.search_process import request_for
    configure(int(sys.argv[1]))
    request = json.loads(Path("request").read_bytes())
    index = request["index"]
    if type(index) is not int or not 0 <= index < len(STRATEGIES):
        raise ValueError("Unknown strategy")
    result = search(request_for(request["research"], request["projection"]), (STRATEGIES[index].family,))
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
