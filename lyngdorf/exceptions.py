class LyngdorfError(Exception):
    """Define a Lyngdorf error."""


class LyngdorfInvalidValueError(LyngdorfError):
    """Define an error when an invalid value is passed to our API."""


class LyngdorfUnsupportedError(LyngdorfError):
    """Raised when asking a device to do something it does not offer.

    The streaming module accepts anything - an unknown play mode returns
    HTTP 200 and is stored - so a request succeeding proves nothing. The
    library refuses up front instead, based on what the device advertises
    for the current source.
    """


class UnsupportedModelError(LyngdorfError):
    """The device at this host did not name a supported model.

    Replaces 1.x's NotImplementedError, which is a builtin that normally
    means "abstract method" — a library should not raise it (spec §2.1).
    """
