"""Project-specific exceptions."""


class ScaleRelayError(Exception):
    """Base exception for expected Scale Relay errors."""


class ConfigError(ScaleRelayError):
    """Configuration is missing or invalid."""


class DependencyMissingError(ScaleRelayError):
    """An optional runtime dependency is not installed."""


class SinkError(ScaleRelayError):
    """A sink failed to send a measurement."""


class MeasurementTimeoutError(ScaleRelayError):
    """No complete measurement was collected before timeout."""


class BleDecryptionError(ScaleRelayError):
    """BLE advertisement decryption failed."""
