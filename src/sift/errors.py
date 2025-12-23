class SiftError(RuntimeError):
    """Base error type."""


class ConfigError(SiftError):
    """Config contract violation."""


class CacheError(SiftError):
    """Cache read/write problem."""


class ProbeError(SiftError):
    """ffprobe execution/parsing problem."""
