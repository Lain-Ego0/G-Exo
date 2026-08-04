"""Thread-safe latest-value cache and health metrics for four IMU streams."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import threading
import time
from typing import Callable

from .config import ImuChannelConfig, TelemetryConfig
from .schemas import ImuReading, ImuTelemetry, ImuTelemetryEnvelope, JointId


@dataclass
class _ChannelState:
    config: ImuChannelConfig
    reading: ImuReading | None = None
    received_wall_ms: float | None = None
    received_monotonic: float | None = None
    arrivals: deque[float] = field(default_factory=deque)


class ImuTelemetryCache:
    def __init__(
        self,
        config: TelemetryConfig,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._lock = threading.Lock()
        self._channels = {
            channel.joint: _ChannelState(channel) for channel in config.channels
        }
        expected = {"left_hip", "left_knee", "right_hip", "right_knee"}
        if set(self._channels) != expected or len(config.channels) != 4:
            raise ValueError("telemetry.channels must define each of the four joints exactly once")
        if config.stale_after_ms <= 0 or config.offline_after_ms <= config.stale_after_ms:
            raise ValueError("offline_after_ms must be greater than stale_after_ms > 0")

    def update(
        self,
        joint: JointId,
        reading: ImuReading,
        received_wall_ms: float | None = None,
        received_monotonic: float | None = None,
    ) -> None:
        wall_ms = received_wall_ms if received_wall_ms is not None else self._wall_clock() * 1000.0
        monotonic = received_monotonic if received_monotonic is not None else self._monotonic_clock()
        with self._lock:
            channel = self._channels[joint]
            channel.reading = reading
            channel.received_wall_ms = wall_ms
            channel.received_monotonic = monotonic
            channel.arrivals.append(monotonic)
            cutoff = monotonic - self._config.frequency_window_s
            while channel.arrivals and channel.arrivals[0] < cutoff:
                channel.arrivals.popleft()

    def snapshot(self) -> ImuTelemetryEnvelope:
        now_mono = self._monotonic_clock()
        generated_at_ms = int(self._wall_clock() * 1000.0)
        with self._lock:
            imus = [self._snapshot_channel(channel, now_mono) for channel in self._ordered_channels()]
        statuses = [imu.status for imu in imus]
        overall = "online" if all(value == "online" for value in statuses) else (
            "offline" if all(value == "offline" for value in statuses) else "degraded"
        )
        return ImuTelemetryEnvelope(
            generated_at_ms=generated_at_ms,
            overall_status=overall,
            imus=imus,
        )

    def _ordered_channels(self) -> list[_ChannelState]:
        return [
            self._channels[joint]  # type: ignore[index]
            for joint in ("left_hip", "left_knee", "right_hip", "right_knee")
        ]

    def _snapshot_channel(self, channel: _ChannelState, now_mono: float) -> ImuTelemetry:
        reading = channel.reading
        if reading is None or channel.received_monotonic is None:
            return ImuTelemetry(
                joint=channel.config.joint,
                topic=channel.config.topic,
                expected_frame_id=channel.config.expected_frame_id,
            )

        age_ms = max(0.0, (now_mono - channel.received_monotonic) * 1000.0)
        if age_ms <= self._config.stale_after_ms:
            status = "online"
        elif age_ms <= self._config.offline_after_ms:
            status = "stale"
        else:
            status = "offline"

        frequency_hz = None
        if len(channel.arrivals) >= 2:
            span = channel.arrivals[-1] - channel.arrivals[0]
            if span > 0:
                frequency_hz = (len(channel.arrivals) - 1) / span

        latency_ms = None
        if reading.timestamp_ms > 0 and channel.received_wall_ms is not None:
            latency_ms = channel.received_wall_ms - reading.timestamp_ms

        return ImuTelemetry(
            joint=channel.config.joint,
            topic=channel.config.topic,
            frame_id=reading.frame_id,
            expected_frame_id=channel.config.expected_frame_id,
            mapping_valid=reading.frame_id == channel.config.expected_frame_id,
            timestamp_ms=reading.timestamp_ms,
            received_at_ms=channel.received_wall_ms,
            orientation=reading.orientation,
            angular_velocity=reading.angular_velocity,
            linear_acceleration=reading.linear_acceleration,
            orientation_covariance_known=reading.orientation_covariance_known,
            status=status,
            online=status == "online",
            stale=status != "online",
            age_ms=age_ms,
            frequency_hz=frequency_hz,
            latency_ms=latency_ms,
        )
