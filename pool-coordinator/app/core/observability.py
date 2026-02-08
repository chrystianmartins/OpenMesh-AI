from __future__ import annotations

import os
import threading
from collections import defaultdict


class PrometheusMetrics:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._lock = threading.Lock()
        self._request_count: dict[tuple[str, str], int] = defaultdict(int)
        self._request_latency_sum: dict[tuple[str, str], float] = defaultdict(float)

    @classmethod
    def from_env(cls) -> "PrometheusMetrics":
        raw = os.getenv("ENABLE_PROMETHEUS_METRICS", "false").strip().lower()
        return cls(enabled=raw in {"1", "true", "yes", "on"})

    def observe_http_request(self, path: str, method: str, elapsed_seconds: float) -> None:
        if not self.enabled:
            return
        key = (path, method)
        with self._lock:
            self._request_count[key] += 1
            self._request_latency_sum[key] += elapsed_seconds

    def render(self) -> str:
        if not self.enabled:
            return "# metrics disabled\n"

        lines = [
            "# HELP http_requests_total Total HTTP requests by path and method.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (path, method), count in sorted(self._request_count.items()):
                lines.append(f'http_requests_total{{path="{path}",method="{method}"}} {count}')

            lines.extend(
                [
                    "# HELP http_request_duration_seconds_sum Total request latency in seconds by path and method.",
                    "# TYPE http_request_duration_seconds_sum counter",
                ]
            )
            for (path, method), total in sorted(self._request_latency_sum.items()):
                lines.append(
                    f'http_request_duration_seconds_sum{{path="{path}",method="{method}"}} {total:.6f}'
                )
        lines.append("")
        return "\n".join(lines)
