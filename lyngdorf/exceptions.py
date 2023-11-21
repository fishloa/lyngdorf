class LyngdorfError(Exception):
    """Define a Lyngdorf error."""


class LyngdorfInvalidValueError(LyngdorfError):
    """Define an error when an invalid value is passed to our API."""

    # pylint: disable=useless-super-delegation
    def __init__(self, message: str, *args, **kwargs) -> None:
        """Create a new instance."""
        super().__init__(message, *args, **kwargs)
