"""Exception types raised by deepyaml."""


class DeepYAMLError(Exception):
    """Base class for all deepyaml errors."""


class ParseError(DeepYAMLError, ValueError):
    """Raised when a config file cannot be parsed."""


class InterpolationError(DeepYAMLError, ValueError):
    """Raised when a ``${...}`` interpolation cannot be resolved."""


class MissingConfigError(DeepYAMLError):
    """Raised when a config directory or required config files cannot be found."""


class DuplicateKeysError(DeepYAMLError, ValueError):
    """Raised when config files in the same directory define the same key.

    Subclasses ``ValueError`` because that is what Kedro's
    ``OmegaConfigLoader`` raises for this condition.
    """
