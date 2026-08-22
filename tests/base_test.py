import logging
import re
from pathlib import Path

from lyngdorf.base import CountingNumberDict

_LOGGER = logging.getLogger(__package__)


def test_counting_dictionary_test():
    cd: CountingNumberDict = CountingNumberDict(3)

    cd.add(0, "zero")
    cd.add(1, "one")
    assert not cd.is_full()
    cd.add(2, "two")

    assert cd.is_full()

    assert 1 == cd.lookupIndex("one")
    assert "zero,one,two" == ",".join(cd.values())

    _LOGGER.debug("nothng to see here")


def test_lyngdorf_does_not_import_attrs():
    """attrs was dropped in 2.0 (spec §7, behavioural change 5) - its one
    use, CountingNumberDict, is a plain class now. attrs may still be
    *installed* (aiohttp depends on it transitively), so this asserts on
    lyngdorf's own source rather than on sys.modules or pip state.
    """
    import lyngdorf

    package_dir = Path(lyngdorf.__file__).parent
    offenders = [
        str(path)
        for path in sorted(package_dir.rglob("*.py"))
        if re.search(r"^\s*(from attr|import attr)", path.read_text(), re.M)
    ]
    assert offenders == []


# def test_model():
#     model=find_receiver_model("192.168.16.16")
