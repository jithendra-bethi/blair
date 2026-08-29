from __future__ import annotations

from blair.errors import AdapterError


class InvalidPayloadError(AdapterError):
    """A hook payload could not be safely normalized."""


class PayloadTooLargeError(InvalidPayloadError):
    """A hook payload exceeded the adapter input limit."""


class UnsupportedEventError(AdapterError):
    """A valid payload described an event this adapter does not handle."""
