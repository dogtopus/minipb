# MiniPB

Mini Protobuf library in pure Python.

![Lint and Run Test Suite](https://github.com/dogtopus/minipb/workflows/Lint%20and%20Run%20Test%20Suite/badge.svg)

## Features

- Pure Python.
- Feature-rich yet lightweight. Even runs on MicroPython.
- Supports struct-like format string, ctypes-like structure representation (i.e. `Structure._field_`) and dataclass-like message class as schema.
- Support schema-less inspection of a given serialized message via `Wire.{encode,decode}_raw` API.
  - Proudly doing this earlier than [protoscope](https://github.com/protocolbuffers/protoscope).

## Getting started

MiniPB supports 3 different flavors of schema declaration methods: Key-value schema (dict serialization), format string (tuple serialization) and message classes (object serialization).

### Key-value schema

```python
import minipb

### Encode/Decode a message with the Wire object and Key-Value Schema
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
```

### Format string

```python
import minipb

### Encode/Decode a message with the Wire object and Format String
hello_world_msg = minipb.Wire('U')

# Encode a message
encoded_msg = hello_world_msg.encode('Hello world!')
# encoded_message == b'\n\x0cHello world!'

# Decode a message
decoded_msg = hello_world_msg.decode(encoded_msg)
# decoded_msg == ('Hello world!',)
```

### Message class

```python
import minipb

### Encode/Decode a Message with schema defined via Fields
@minipb.process_message_fields
class HelloWorldMessage(minipb.Message):
    msg = minipb.Field(1, minipb.TYPE_STRING)

# Creating a Message instance
#   Method 1: init with kwargs work!
msg_obj = HelloWorldMessage(msg='Hello world!')

#   Method 2: from_dict, iterates over all Field's declared in order on the class
msg_obj = HelloWorldMessage.from_dict({'msg': 'Hello world!'})

# Encode a message
encoded_msg = msg_obj.encode()
# encoded_message == b'\n\x0cHello world!'

# Decode a message
decoded_msg_obj = HelloWorldMessage.decode(encoded_msg)
# decoded_msg == HelloWorldMessage(msg='Hello world!')

decoded_dict = decoded_msg_obj.to_dict()
# decoded_dict == {'msg': 'Hello world!'}
```

Refer to the [Schema Representation][schema] for detailed explanation on schema formats accepted by MiniPB.

## Installation

### CPython, PyPy, etc.

Install via pip

```sh
pip install git+https://github.com/dogtopus/minipb
```

### MicroPython

**NOTE (Old data but still somewhat relevant)**: Despite being lightweight compared to official Protobuf, the `minipb` module itself still uses around 15KB of RAM after loaded via `import`. Therefore it is recommended to use MiniPB on MicroPython instances with minimum of 24KB of memory available to the scripts. Instances with at least 48KB of free memory is recommended for more complex program logic.

On targets with plenty of RAM, such as Pyboards and the Unix build, installation consists of copying `minipb.py` to the filesystem and installing the `logging` and `bisect` module from [micropython-lib][mpylib]. For targets with restricted RAM there are two options: cross compilation and frozen bytecode. The latter offers the greatest saving. See the [official docs][mpydoc] for further explanation.

Cross compilation may be achieved as follows. First you need `mpy-cross` that is compatible with the mpy version you are using.

Compile MiniPB by using

```sh
mpy-cross -s minipb.py minipb/minipb.py -o /your/PYBFLASH/minipb.mpy
```

You also need `logging` and `bisect` module from [micropython-lib][mpylib]. Compile it by using

```sh
mpy-cross -s logging.py micropython-lib/logging/logging.py -o /your/PYBFLASH/logging.mpy
mpy-cross -s bisect.py micropython-lib/bisect/bisect.py -o /your/PYBFLASH/bisect.mpy
```

Unmount PYBFLASH and reset the board when both files are installed to your MicroPython instance.

On production deployment, it is possible to run `mpy-cross` with `-O` set to higher than 0 to save more flash and RAM usage by sacrificing some debuggability. For example `-O3` saves about 1KB of flash and library RAM usage while disables assertion and removes source line numbers during traceback.

```sh
mpy-cross -s minipb.py -O3 minipb/minipb.py -o /your/PYBFLASH/minipb.mpy
mpy-cross -s logging.py -O3 micropython-lib/logging/logging.py -o /your/PYBFLASH/logging.mpy
mpy-cross -s bisect.py -O3 micropython-lib/bisect/bisect.py -o /your/PYBFLASH/bisect.mpy
```

## Usage

Detailed documentation can be found under the project [Wiki][wiki]. The module's pydoc contains some useful information about the API too.

[mpylib]: https://github.com/micropython/micropython-lib
[wiki]: https://github.com/dogtopus/minipb/wiki
[schema]: https://github.com/dogtopus/minipb/wiki/Schema-Representations
[mpydoc]: http://docs.micropython.org/en/latest/reference/packages.html
