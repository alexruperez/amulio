import json
import logging
import sys
import time
from collections import defaultdict
from threading import Lock


class JsonFormatter(logging.Formatter):
    """Emit application logs as one JSON document per line."""

    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    logger = logging.getLogger("amulio")
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class MetricsRegistry:
    """Small dependency-free Prometheus registry for process-local HTTP metrics."""

    _buckets = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._durations: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._started_at = time.monotonic()

    def observe_request(
        self, *, method: str, route: str, status_code: int, duration: float
    ) -> None:
        with self._lock:
            self._requests[(method, route, status_code)] += 1
            self._durations[(method, route)].append(duration)

    @staticmethod
    def _labels(**labels: object) -> str:
        return "{" + ",".join(f'{key}="{value}"' for key, value in labels.items()) + "}"

    def render_prometheus(self) -> str:
        with self._lock:
            lines = [
                "# HELP amulio_http_requests_total HTTP requests completed by aMulio.",
                "# TYPE amulio_http_requests_total counter",
            ]
            for (method, route, status_code), count in sorted(self._requests.items()):
                lines.append(
                    "amulio_http_requests_total"
                    + self._labels(method=method, route=route, status=status_code)
                    + f" {count}"
                )
            lines.extend(
                [
                    "# HELP amulio_http_request_duration_seconds HTTP request duration.",
                    "# TYPE amulio_http_request_duration_seconds histogram",
                ]
            )
            for (method, route), durations in sorted(self._durations.items()):
                for bucket in self._buckets:
                    count = sum(duration <= bucket for duration in durations)
                    lines.append(
                        "amulio_http_request_duration_seconds_bucket"
                        + self._labels(method=method, route=route, le=bucket)
                        + f" {count}"
                    )
                lines.append(
                    "amulio_http_request_duration_seconds_bucket"
                    + self._labels(method=method, route=route, le="+Inf")
                    + f" {len(durations)}"
                )
                lines.append(
                    "amulio_http_request_duration_seconds_count"
                    + self._labels(method=method, route=route)
                    + f" {len(durations)}"
                )
                lines.append(
                    "amulio_http_request_duration_seconds_sum"
                    + self._labels(method=method, route=route)
                    + f" {sum(durations):.9f}"
                )
            lines.extend(
                [
                    "# HELP amulio_process_uptime_seconds Seconds since aMulio started.",
                    "# TYPE amulio_process_uptime_seconds gauge",
                    f"amulio_process_uptime_seconds {time.monotonic() - self._started_at:.6f}",
                ]
            )
        return "\n".join(lines) + "\n"
