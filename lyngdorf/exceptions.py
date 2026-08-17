class LyngdorfError(Exception):
    """Define a Lyngdorf error."""


class LyngdorfInvalidValueError(LyngdorfError):
    """Define an error when an invalid value is passed to our API."""

    # pylint: disable=useless-super-delegation
    def __init__(self, message: str, *args, **kwargs) -> None:
        """Create a new instance."""
        super().__init__(message, *args, **kwargs)


class LyngdorfUnsupportedError(LyngdorfError):
    """Raised when asking a device to do something it does not offer.

    The streaming module accepts anything - an unknown play mode returns
    HTTP 200 and is stored - so a request succeeding proves nothing. The
    library refuses up front instead, based on what the device advertises
    for the current source.
    """
