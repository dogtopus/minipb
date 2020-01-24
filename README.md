# MiniPB

Mini Protobuf library in pure Python.

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

Format string documentation can be found under doc/format_str. The module's pydoc contains some useful information on the API too.

[mpylib]: https://github.com/micropython/micropython-lib
