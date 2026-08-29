class BlairError(Exception):
    """Base class for expected, user-actionable BLAIR errors."""


class TtsError(BlairError):
    """Local speech synthesis failed."""


class AdapterError(BlairError):
    """An agent completion payload was invalid or unsupported."""
