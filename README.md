# MiniPB

Mini Protobuf library in pure Python.

![Python package](https://github.com/dogtopus/minipb/workflows/Python%20package/badge.svg)

## Features

- Pure Python.
- Feature-rich yet lightweight. Even runs on MicroPython.
- Supports both struct-like format string and ctypes-like structure representation (i.e. `Structure._field_`) as schema.
- Support schema-less inspection of a given serialized message via the `RawWire` API.

## Getting started

```python
import minipb

# Create the Wire object with schema
hello_world_msg = minipb.Wire([
    ('msg', 'U') # 'U' means UTF-8 string.
])

# Encode a message
encoded_msg = hello_world_msg.encode({
    'msg': 'Hello world!'
})
# encoded_message == b'\n\x0cHello world!'

# Decode a message
decoded_msg = hello_world_msg.decode(encoded_msg)
# decoded_msg == {'msg': 'Hello world!'}

# Alternatively, use the format string
hello_world_msg = minipb.Wire('U')

# Encode a message
encoded_msg = hello_world_msg.encode('Hello world!')
# encoded_message == b'\n\x0cHello world!'

# Decode a message
decoded_msg = hello_world_msg.decode(encoded_msg)
# decoded_msg == ('Hello world!',)
```

Refer to the [Schema Representation][schema] for detailed explanation on schema formats accepted by MiniPB.

## Installation

### CPython, PyPy, etc.

Install via pip

```sh
pip install git+https://github.com/dogtopus/minipb
```

### MicroPython

**NOTE**: Despite being lightweight compared to official Protobuf, the `minipb` module itself still uses around 15KB of RAM after loaded via `import`. Therefore it is recommended to use MiniPB on MicroPython instances with minimum of 24KB of memory available to the scripts. Instances with at least 48KB of free memory is recommended for more complex program logic.

First you need `mpy-cross` that is compatible with the mpy version you are using.

Compile MiniPB by using

```sh
mpy-cross minipb/minipb.py -o /your/PYBFLASH/minipb.mpy
```

You also need `logging` module from [micropython-lib][mpylib]. Compile it by using

```sh
mpy-cross micropython-lib/logging/logging.py -o /your/PYBFLASH/logging.mpy
```

Unmount PYBFLASH and reset the board when both files are installed to your MicroPython instance.

## Usage

Format string documentation can be found under the project [Wiki][wiki]. The module's pydoc contains some useful information on the API too.

[mpylib]: https://github.com/micropython/micropython-lib
[wiki]: https://github.com/dogtopus/minipb/wiki
[schema]: https://github.com/dogtopus/minipb/wiki/Schema-Representations
