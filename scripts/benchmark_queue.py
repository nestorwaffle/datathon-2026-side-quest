"""Small local-only queue benchmark; never calls a model or RawTree."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", default="devflight/core.py")
    parser.add_argument("--events", type=int, default=200)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("bench_core", args.core)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    with tempfile.TemporaryDirectory() as home:
        queue = core.Queue(home, rotate_bytes=10_000_000)
        trace = core.Trace(queue)
        cpu = time.process_time()
        start = time.perf_counter()
        for number in range(args.events):
            trace.emit("tool.result", {"synthetic": True, "number": number})
        append_seconds = time.perf_counter() - start
        start = time.perf_counter()
        for _ in range(20):
            status = queue.status()
        print(json.dumps({"events": args.events, "append_seconds": append_seconds,
                          "status_mean_seconds": (time.perf_counter() - start) / 20,
                          "cpu_seconds": time.process_time() - cpu,
                          "bytes": queue.active.stat().st_size, "pending": status["pending"],
                          "source": args.core, "network_bytes": 0}))

if __name__ == "__main__":
    main()
