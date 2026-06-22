"""Exceptions raised by deepyaml."""

from __future__ import annotations


class DeepYAMLError(Exception):
    """Base class for all deepyaml errors."""


class InterpolationError(DeepYAMLError):
    """A ``${...}`` interpolation could not be resolved."""


class MergeError(DeepYAMLError):
    """Configuration files could not be merged (e.g. duplicate keys)."""


class MissingConfigError(DeepYAMLError):
    """No configuration files matched the requested patterns."""
