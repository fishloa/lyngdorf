# lyngdorf

Automation Library for Lyngdorf receivers

## Installation

Use pip:

```$ pip install lyngdorf```

or 

```$ pip install --use-wheel lyngdorf```

## Usage

Primarily designed to be used by Home Assistant, this library can be used as follows:

```
>>> from lyngdorf.mp60 import LyngdorfMP60Client
>>> mp60 = LyngdorfMP60Client("192.168.16.16")
>>> await mp60.async_connect()
>>> mp60.power_on(True)
>>> print(mp60.volume)
-36.5
>>> mp60.volume=-22.5
>>> print(mp60.volume)
--22.5

```
  