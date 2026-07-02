"""Exception types raised by deepyaml."""


class DeepYAMLError(Exception):
    """Base class for all deepyaml errors."""


class ParseError(DeepYAMLError, ValueError):
    """Raised when a config file cannot be parsed."""
