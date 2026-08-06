from __future__ import annotations

from gexo_web_agent.config import TelemetryConfig
from gexo_web_agent.imu_cache import ImuTelemetryCache
from gexo_web_agent.schemas import ImuReading, QuaternionData, Vector3Data
from gexo_web_agent.telemetry_api import create_telemetry_app


def reading(frame_id: str = "A1_link", timestamp_ms: float = 1_000.0) -> ImuReading:
    return ImuReading(
        frame_id=frame_id,
        timestamp_ms=timestamp_ms,
        orientation=QuaternionData(x=0.0, y=0.0, z=0.0, w=1.0),
        angular_velocity=Vector3Data(x=1.0, y=2.0, z=3.0),
        linear_acceleration=Vector3Data(x=4.0, y=5.0, z=6.0),
        orientation_covariance_known=False,
    )


def test_empty_cache_has_four_offline_channels() -> None:
    envelope = ImuTelemetryCache(TelemetryConfig()).snapshot()
    assert envelope.overall_status == "offline"
    assert [imu.joint for imu in envelope.imus] == ["left_hip", "left_knee", "right_hip", "right_knee"]
    assert all(imu.status == "offline" and imu.orientation is None for imu in envelope.imus)


def test_cache_tracks_frequency_latency_and_mapping() -> None:
    cache = ImuTelemetryCache(
        TelemetryConfig(),
        wall_clock=lambda: 1.006,
        monotonic_clock=lambda: 0.006,
    )
    cache.update("left_hip", reading(timestamp_ms=1_000.0), received_wall_ms=1_001.0, received_monotonic=0.0)
    cache.update("left_hip", reading(timestamp_ms=1_005.0), received_wall_ms=1_006.0, received_monotonic=0.005)
    envelope = cache.snapshot()
    imu = envelope.imus[0]
    assert imu.status == "online"
    assert imu.mapping_valid is True
    assert imu.frequency_hz == 200.0
    assert imu.latency_ms == 1.0


def test_cache_marks_one_channel_stale_without_affecting_others() -> None:
    cache = ImuTelemetryCache(
        TelemetryConfig(),
        wall_clock=lambda: 1.2,
        monotonic_clock=lambda: 0.2,
    )
    cache.update("left_hip", reading(), received_wall_ms=1_000.0, received_monotonic=0.0)
    cache.update("left_knee", reading("A2_link"), received_wall_ms=1_000.0, received_monotonic=0.0)
    envelope = cache.snapshot()
    assert envelope.imus[0].status == "stale"
    assert envelope.imus[1].status == "stale"


def test_frame_mismatch_is_reported_without_dropping_sample() -> None:
    cache = ImuTelemetryCache(
        TelemetryConfig(),
        wall_clock=lambda: 1.001,
        monotonic_clock=lambda: 0.001,
    )
    cache.update("left_hip", reading("wrong_frame"), received_wall_ms=1_000.0, received_monotonic=0.0)
    imu = cache.snapshot().imus[0]
    assert imu.frame_id == "wrong_frame"
    assert imu.mapping_valid is False
    assert imu.orientation is not None


class FakeTransport:
    def __init__(self) -> None:
        self.callback = None
        self.started = False

    def set_sample_callback(self, callback) -> None:
        self.callback = callback

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


def test_telemetry_api_is_read_only_and_uses_imu_contract() -> None:
    from fastapi.testclient import TestClient
    from gexo_web_agent.config import Settings

    settings = Settings()
    settings.telemetry.enabled = True
    cache = ImuTelemetryCache(settings.telemetry)
    transport = FakeTransport()
    app = create_telemetry_app(settings, cache, transport)

    with TestClient(app) as client:
        assert transport.started
        health = client.get("/health").json()
        assert health["mode"] == "telemetry_only"
        payload = client.get("/api/telemetry").json()
        assert payload["schema_version"] == "imu.v1"
        assert len(payload["imus"]) == 4
        assert client.post("/api/action", json={}).status_code == 405
    assert not transport.started
