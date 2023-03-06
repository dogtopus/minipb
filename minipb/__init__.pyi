from __future__ import annotations

from typing import (
    Union,
    Tuple,
    List,
    TypedDict,
    Sequence,
    Dict,
    Any,
    Literal,
    Optional,
    overload,
)

import logging

BytesLike = Union[bytes, bytearray, memoryview]
WireIRData = Union[BytesLike, int, float]

KVFormatSpec = Sequence[
    Union[
        Tuple[str, str], # name, type
        Tuple[str, 'KVFormatSpec'], # name, other_schema
        Tuple[str, str, 'KVFormatSpec'], # name, type, other_schema
    ]
]

FormatSpec = Union[KVFormatSpec, str]

class WireIR(TypedDict):
    id: int
    wire_type: int
    data: WireIRData


class BadFormatString(ValueError): ...
class CodecError(Exception): ...

class EndOfMessage(EOFError):
    @property
    def partial(self) -> bool: ...

class Wire:
    logger: logging.Logger
    allow_sparse_dict: bool
    def __init__(self, fmt: FormatSpec, vint_2sc_max_bits: Optional[int] = ..., allow_sparse_dict: bool = ...) -> None: ...
    @property
    def vint_2sc_max_bits(self) -> int: ...
    @vint_2sc_max_bits.setter
    def vint_2sc_max_bits(self, bits: int) -> None: ...
    @property
    def kvfmt(self) -> bool: ...
    def encode(self, *stuff: Any) -> bytes: ...
    def decode(self, data: BytesLike) -> Union[Sequence[Any], Dict[str, Any]]: ...
    @classmethod
    def encode_raw(self, stuff: WireIR) -> bytes: ...
    @classmethod
    def decode_raw(self, data: BytesLike) -> WireIR: ...

def encode(fmtstr: FormatSpec, *stuff: Any) -> bytes: ...
def decode(fmtstr: FormatSpec, data: BytesLike) -> Union[Sequence[Any], Dict[str, Any]]: ...
def encode_raw(objs: WireIR) -> bytes: ...
def decode_raw(data: BytesLike) -> WireIR: ...
