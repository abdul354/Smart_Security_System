import threading
import time
from collections import defaultdict, deque
from typing import Dict, Iterable, Tuple

_METRIC_WINDOW = 240
_METRIC_HORIZON = 15.0
_METRICS: Dict[str, deque[Tuple[float, float]]] = defaultdict(lambda: deque(maxlen=_METRIC_WINDOW))
_LOCK = threading.Lock()


def record(metric: str, value: float) -> None:
    """Store a timestamped metric sample for rolling diagnostics."""
    ts = time.time()
    with _LOCK:
        _METRICS[metric].append((ts, float(value)))


def snapshot(horizon: float = _METRIC_HORIZON) -> Dict[str, Dict[str, float]]:
    """Return aggregate stats for recent samples within *horizon* seconds."""
    now = time.time()
    summary: Dict[str, Dict[str, float]] = {}
    with _LOCK:
        for name, samples in _METRICS.items():
            filtered = [value for ts, value in samples if now - ts <= horizon]
            if not filtered:
                continue
            summary[name] = {
                "avg": float(sum(filtered) / len(filtered)),
                "max": float(max(filtered)),
                "min": float(min(filtered)),
                "samples": float(len(filtered)),
            }
    return summary


def purge(metric: str) -> None:
    with _LOCK:
        _METRICS.pop(metric, None)


def reset(metrics: Iterable[str] | None = None) -> None:
    with _LOCK:
        if metrics is None:
            _METRICS.clear()
        else:
            for name in metrics:
                _METRICS.pop(name, None)
