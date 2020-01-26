# MiniPB

Mini Protobuf library in pure Python.

![Python package](https://github.com/dogtopus/minipb/workflows/Python%20package/badge.svg)

## Features

- Pure Python.
- Feature-rich yet lightweight. Even runs on MicroPython.
- Supports both struct-like format string and ctypes-like structure representation (i.e. `Structure._field_`) as schema.
- Support schema-less inspection of a given serialized message via the `RawWire` API.

## Installation

### CPython, PyPy, etc.

Install via pip

```sh
pip install git+https://github.com/dogtopus/minipb
```

### MicroPython

First you need `mpy-cross` that is compatible with the mpy version you are using.

Compile MiniPB by using

```sh
mpy-cross minipb/minipb.py -o /your/PYBFLASH/minipb.mpy
```

You also need `logging` module from [micropython-lib][mpylib]. Compile it by using

```sh
mpy-cross micropython-lib/logging/logging.py -o /your/PYBFLASH/logging.mpy
```

Unmount and reset when both files are installed to your MicroPython instance.

## Usage

Format string documentation can be found under the project [Wiki][wiki]. The module's pydoc contains some useful information on the API too.

[mpylib]: https://github.com/micropython/micropython-lib
[wiki]: https://github.com/dogtopus/minipb/wiki
