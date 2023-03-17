###############################################################################
#
# minipb.py
#
# SPDX-License-Identifier: BSD-3-Clause
#

"""
Mini Protobuf library

minipb uses simple schema representation to serialize and deserialize data
between Python data types and Protobuf binary wire messages.
Compare to original Protobuf, it is more light-weight, simple and therefore
can be used in resource limited systems, quick protocol prototyping and
reverse-engineering of unknown Protobuf messages.
"""

import collections
import bisect
import logging
import re
import struct
import io

mod_logger = logging.getLogger('minipb')

_IS_MPY = __import__('sys').implementation.name == 'micropython'

#
# Protocol Buffer types, as used in minipb
# https://protobuf.dev/programming-guides/proto3/
#
TYPE_DOUBLE = 'd'
TYPE_FLOAT = 'f'
TYPE_INT = 't'
TYPE_UINT = 'T'
TYPE_SINT = 'z'
TYPE_FIXED32 = 'I'
TYPE_FIXED64 = 'Q'
TYPE_SFIXED32 = 'i'
TYPE_SFIXED64 = 'q'
TYPE_BOOL = 'b'
TYPE_STRING = 'U'
TYPE_BYTES = 'a'
TYPE_EMPTY = 'x'

# Within MiniPB, all these types are handled the same way, simplifying to INT, UINT, and SINT
TYPE_INT32 = TYPE_INT
TYPE_INT64 = TYPE_INT
TYPE_UINT32 = TYPE_UINT
TYPE_UINT64 = TYPE_UINT
TYPE_SINT32 = TYPE_SINT
TYPE_SINT64 = TYPE_SINT

TYPES = frozenset([
    TYPE_DOUBLE, TYPE_FLOAT, TYPE_INT, TYPE_UINT, TYPE_SINT, TYPE_FIXED32, TYPE_FIXED64, TYPE_SFIXED32, TYPE_SFIXED64, TYPE_BOOL, TYPE_STRING, TYPE_BYTES, TYPE_EMPTY,
    'v', 'V', 'l', 'L'
])

#
# Protocol Buffer wire types, defined in official documentation
# https://protobuf.dev/programming-guides/encoding/#structure
# 
_WIRE_TYPE_VARINT = 0
_WIRE_TYPE_I64 = 1
_WIRE_TYPE_LEN = 2
_WIRE_TYPE_I32 = 5

#
# Protocol Buffer Type to Wire Type mapping, defined in official documentation
# https://protobuf.dev/programming-guides/encoding/#structure
#
_TYPE_TO_WIRE_TYPE_MAP = {
    # VARINT
    TYPE_INT: _WIRE_TYPE_VARINT,
    TYPE_UINT: _WIRE_TYPE_VARINT,
    TYPE_SINT: _WIRE_TYPE_VARINT,
    TYPE_BOOL: _WIRE_TYPE_VARINT,

    # I64
    TYPE_FIXED64: _WIRE_TYPE_I64,
    TYPE_SFIXED64: _WIRE_TYPE_I64,
    TYPE_DOUBLE: _WIRE_TYPE_I64,

    # LEN
    TYPE_STRING: _WIRE_TYPE_LEN,
    TYPE_BYTES: _WIRE_TYPE_LEN,

    # I32
    TYPE_FIXED32: _WIRE_TYPE_I32,
    TYPE_SFIXED32: _WIRE_TYPE_I32,
    TYPE_FLOAT: _WIRE_TYPE_I32,

    TYPE_EMPTY: None
}

#
# Errors raised by minipb
# 
class BadFormatString(ValueError):
    """
    Malformed format string
    """
    pass


class CodecError(Exception):
    """
    Error during serializing or deserializing
    """
    pass


class EndOfMessage(EOFError):
    """
    Reached end of Protobuf message while deserializing fields.
    """
    @property
    def partial(self):
        """
        True if the data was partially read.
        """
        if len(self.args) > 0:
            return self.args[0]
        else:
            return False


if _IS_MPY:
    # MicroPython re hack
    def _get_length_of_match(m):
        return len(m.group(0))
else:
    def _get_length_of_match(m):
        return m.end()

#
# Encoders/Decoders for Protocol Buffer's basic types
#
def _encode_vint(number):
    """
    Encode a number to vint (Wire Type 0).
    Numbers can only be signed or unsigned. Any number less than 0 must
    be processed either using zigzag or 2's complement (2sc) before
    passing to this function.
    Called internally in _encode_field() function
    """

    assert number >= 0, 'number is less than 0'
    result = bytearray()
    while 1:
        tmp = number & 0x7f
        number >>= 7
        if number == 0:
            result.append(tmp)
            break
        result.append(0x80 | tmp)
    return bytes(result)

def _decode_vint(buf):
    """
    Decode vint encoded integer.
    Raises EndOfMessage if there is no or only partial data available.
    Called internally in decode() method.
    """
    ctr = 0
    result = 0
    tmp = bytearray(1)
    partial = False
    while 1:
        count = buf.readinto(tmp)
        if count == 0:
            raise EndOfMessage(partial)
        else:
            partial = True
        result |= (tmp[0] & 0x7f) << (7 * ctr)
        if not (tmp[0] >> 7): break
        ctr += 1
    return result

_DEFAULT_VINT_2SC_MAX_BITS = 64
_DEFAULT_VINT_2SC_MASK = (1 << _DEFAULT_VINT_2SC_MAX_BITS) - 1
def _vint_signedto2sc(number, mask=_DEFAULT_VINT_2SC_MASK):
    """
    Perform Two's Complement encoding
    Called internally in _encode_field() function
    """
    return number & mask


def _vint_2sctosigned(number, max_bits=_DEFAULT_VINT_2SC_MAX_BITS, mask=_DEFAULT_VINT_2SC_MASK):
    """
    Decode Two's Complement encoded integer (which were treated by the
    'shallow' decoder as unsigned vint earlier) to normal signed integer
    Called internally in _decode_field() function
    """
    assert number >= 0, 'number is less than 0'
    if (number >> (max_bits - 1)) & 1:
        number = ~(~number & mask)
    return number

def _vint_zigzagify(number):
    """
    Perform zigzag encoding
    Called internally in _encode_field() function
    """
    num = number << 1
    if number < 0:
        num = ~num
    return num

def _vint_dezigzagify(number):
    """
    Convert zigzag encoded integer to its original form.
    Called internally in _decode_field() function
    """

    assert number >= 0, 'number is less than 0'
    is_neg = number & 1
    num = number >> 1
    if is_neg:
        num = ~num
    return num

def _encode_bytes(in_bytes):
    """
    Encode a string/binary stream into protobuf variable length by
    appending a special header containing the length of the string.
    Called internally in _encode_field() function
    """
    result = _encode_vint(len(in_bytes))
    result += in_bytes
    return result

def _decode_bytes(buf):
    """
    Decode Protobuf variable length string to Python string.
    Raises EndOfMessage if there is no or only partial data available.
    Called internally in _decode_field() function.
    """
    length = _decode_vint(buf)
    result = buf.read(length)
    if len(result) != length:
        raise EndOfMessage(True)
    return result

def _encode_fixed_length_numerical(field_type, py_data, mask=None):
    return struct.pack('<{0}'.format(field_type), py_data)

def _decode_fixed_length_numerical(field_type, field_bytes, max_bits=None, mask=None):
    return struct.unpack('<{0}'.format(field_type), field_bytes)[0]
        

_TYPE_TO_ENCODER_MAP = {
    TYPE_BYTES:    lambda t, py_data, mask: _encode_bytes(py_data),
    TYPE_STRING:   lambda t, py_data, mask: _encode_bytes(py_data.encode('utf-8')),
    TYPE_INT:      lambda t, py_data, mask: _encode_vint(_vint_signedto2sc(py_data, mask=mask)),
    TYPE_UINT:     lambda t, py_data, mask: _encode_vint(py_data),
    TYPE_SINT:     lambda t, py_data, mask: _encode_vint(_vint_zigzagify(py_data)),
    TYPE_BOOL:     lambda t, py_data, mask: _encode_vint(int(py_data)),
    TYPE_SFIXED32: _encode_fixed_length_numerical,
    TYPE_FIXED32:  _encode_fixed_length_numerical,
    TYPE_FLOAT:    _encode_fixed_length_numerical,
    TYPE_DOUBLE:   _encode_fixed_length_numerical,
    TYPE_SFIXED64: _encode_fixed_length_numerical,
    TYPE_FIXED64:  _encode_fixed_length_numerical
}

_TYPE_TO_DECODER_MAP = {
    TYPE_BYTES:    lambda t, f_data, max_bits, mask: f_data,
    TYPE_STRING:   lambda t, f_data, max_bits, mask: f_data.decode('utf-8'),
    TYPE_INT:      lambda t, f_data, max_bits, mask: _vint_2sctosigned(f_data, max_bits=max_bits, mask=mask),
    TYPE_UINT:     lambda t, f_data, max_bits, mask: f_data,
    TYPE_SINT:     lambda t, f_data, max_bits, mask: _vint_dezigzagify(f_data),
    TYPE_BOOL:     lambda t, f_data, max_bits, mask: bool(f_data != 0),
    TYPE_SFIXED32: _decode_fixed_length_numerical,
    TYPE_FIXED32:  _decode_fixed_length_numerical,
    TYPE_FLOAT:    _decode_fixed_length_numerical,
    TYPE_DOUBLE:   _decode_fixed_length_numerical,
    TYPE_SFIXED64: _decode_fixed_length_numerical,
    TYPE_FIXED64:  _decode_fixed_length_numerical
}
def _encode_scalar_to_bytes(field_type, py_data, mask=_DEFAULT_VINT_2SC_MASK):
    """
    Encode a single field to binary wire format, without field_number and wire_type headers
    
    This method does NOT support nested Messages
    """
    encoder_fxn = _TYPE_TO_ENCODER_MAP.get(field_type)
    if not encoder_fxn:
        raise TypeError('unknown type: {}'.format(field_type))

    return encoder_fxn(field_type, py_data, mask)

def _decode_scalar_from_bytes(field_type, f_data, max_bits=_DEFAULT_VINT_2SC_MAX_BITS, mask=_DEFAULT_VINT_2SC_MASK):
    """
    Decode a single field, without field_number and wire_type headers

    This method does NOT support nested Messages
    """
    decoder_fxn = _TYPE_TO_DECODER_MAP.get(field_type)
    if not decoder_fxn:
        raise TypeError('unknown type: {}'.format(field_type))

    return decoder_fxn(field_type, f_data, max_bits=max_bits, mask=mask)

#
# Helper functions when processing Protocol Buffer Wire formats without schemas
#
def _encode_header(f_type, f_id):
    """
    Encode a header
    Called internally in _encode_wire() function
    """
    hdr = (f_id << 3) | f_type
    return _encode_vint(hdr)

def _decode_header(buf):
    """
    Decode field header.
    Raises EndOfMessage if there is no or only partial data available.
    Called internally in decode() method
    """
    ord_data = _decode_vint(buf)
    f_type = ord_data & 7
    f_id = ord_data >> 3
    return f_type, f_id

def _check_bytes_length(data, length):
    if not hasattr(data, 'decode'):
        raise ValueError(
            'Excepted a bytes object, not {}'.format(
                type(data).__name__
            )
        )
    elif len(data) != length:
        raise ValueError(
            'Excepted a bytes object of length {}, got {}'.format(
                length, len(data)
            )
        )
    return data

def _read_fixed(buf, length):
    """
    Read out a fixed type and report if the result is incomplete.
    Called internally in _yield_fields_from_wire().
    """
    result = buf.read(length)
    actual = len(result)
    if actual != length:
        raise EndOfMessage(False if actual == 0 else True)
    return result


_WIRE_TYPE_TO_ENCODER_MAP = {
    _WIRE_TYPE_VARINT: _encode_vint,
    _WIRE_TYPE_I64:    lambda n: _check_bytes_length(n, 8),
    _WIRE_TYPE_LEN:    _encode_bytes,
    _WIRE_TYPE_I32:    lambda n: _check_bytes_length(n, 4)
}

_WIRE_TYPE_TO_DECODER_MAP = {
    _WIRE_TYPE_VARINT:  _decode_vint,
    _WIRE_TYPE_I64:     lambda n: _read_fixed(n, 8),
    _WIRE_TYPE_LEN:     _decode_bytes,
    _WIRE_TYPE_I32:     lambda n: _read_fixed(n, 4)
}
def _yield_fields_from_wire(buf, wire_type=None, field_number=None):
    """
    Helper method to 'break down' a wire string into a list for
    further processing.
    Pass type_override and id_override to decompose headerless wire
    strings. (Mainly used for unpacking packed repeated fields)
    Called internally in _decode_wire() function
    """
    assert (field_number is not None and wire_type is not None) or\
            (field_number is None and wire_type is None),\
        'Field ID and type must be both specified in headerless mode'

    requires_header_decoding = (wire_type is None and field_number is None)
    while 1:
        field = {}
        if requires_header_decoding:
            # if no more data, stop and return
            try:
                wire_type, field_number = _decode_header(buf)
            except EOFError:
                break

        wt_decoder = _WIRE_TYPE_TO_DECODER_MAP.get(wire_type)
        if not wt_decoder:
            mod_logger.warning(
                "_yield_fields_from_wire():Ignore unknown type #%d", wire_type
            )
            continue
        try:
            f_data = wt_decoder(buf)
        except EndOfMessage as e:
            if wire_type is None or e.partial:
                raise CodecError('Unexpected end of message while decoding field {0}'.format(field_number)) from e
            else:
                break
        field['id'] = field_number
        field['wire_type'] = wire_type
        field['data'] = f_data
        yield field

def encode_raw(objs):
    """
    Encode a list of raw data and types to binary wire format
    Useful for analyzing Protobuf messages with unknown schema

    Encode the output of decode_raw() back to binary wire format
    """
    encoded = io.BytesIO()
    for s in objs:
        wire_type = s['wire_type']
        encoded.write(_encode_header(wire_type, s['id']))
        current_encoder = _WIRE_TYPE_TO_ENCODER_MAP.get(wire_type)
        if not current_encoder:
            raise ValueError('Unknown type {}'.format(wire_type))
        encoded.write(current_encoder(s['data']))

    return encoded.getvalue()


def decode_raw(data):
    """
    Decode given binary wire to a list of raw data and types
    Useful for analyzing Protobuf messages with unknown schema

    Decode wire data to a list of dicts that contain raw wire data and types
    The dictionary contains 3 keys:
        - id: The field number that the data belongs to
        - wire_type: Wire type of that field, see
            https://developers.google.com/protocol-buffers/docs/encoding
            for the list of wire types (currently type 3 and 4 are not
            supported)
        - data: The raw data of the field. Note that data with wire type 0
            (vints) are always decoded as unsigned Two's Complement format
            regardless of ZigZag encoding was being used (which also means
            they will always be positive) and wire type 1 and 5 (fixed-length)
            are decoded as bytes of fixed length (i.e. 8 bytes for type 1 and
            4 bytes for type 5)
    """
    if not hasattr(data, 'read'):
        data = io.BytesIO(data)

    return tuple(_yield_fields_from_wire(data))

#
# Characters explicitly used in minipb's format_string and kvfmt schema 
#
PREFIX_REQUIRED = '*'
PREFIX_REPEATED = '+'
PREFIX_REPEATED_PACKED = '#'
PREFIX_MESSAGE = '['

SUFFIX_MESSAGE = ']'
class _OverlapCheck:
    '''
    Check overlaps of fields and keep track used field intervals.
    Used internally in Wire schema parsers.
    '''
    def __init__(self):
        self._parser_used_fields = None

    def _check_overlap(self, start, span=1):
        '''
        Helper method that keep track on overlapping fields.
        Called internally in add_field.
        '''
        parser_used_fields = self._parser_used_fields

        # Decide actual end point
        end = start + span

        if parser_used_fields is None:
            self._parser_used_fields = [start, end]
            return True

        # Append at the end (happy path)
        if start == parser_used_fields[-1]:
            parser_used_fields[-1] = end
            return True
        if start > parser_used_fields[-1]:
            parser_used_fields.extend((start, end))
            return True

        # Prepend at the beginning
        if end == parser_used_fields[0]:
            parser_used_fields[0] = start
            return True
        if end < parser_used_fields[0]:
            parser_used_fields.insert(0, end)
            parser_used_fields.insert(0, start)
            return True

        # Determine insertion point
        offset = bisect.bisect_right(parser_used_fields, start)

        # Insertion point is within a single interval. Definitely overlapping.
        if offset % 2 != 0:
            return False

        gap_start, gap_end = parser_used_fields[offset-1], parser_used_fields[offset]
        # Check if end is in another interval or gap. If so there's an overlap.
        if end > gap_end:
            return False

        # New interval in-between 2 existing intervals
        if gap_start != start and gap_end != end:
            parser_used_fields.insert(offset, end)
            parser_used_fields.insert(offset, start)
        # Only start is equal. Extending right side interval
        elif gap_end != end:
            parser_used_fields[offset-1] = end
        # Only end is equal. Extending left side interval
        elif gap_start != start:
            parser_used_fields[offset] = start
        # Both are equal. Connecting 2 intervals
        else:
            del parser_used_fields[offset-1]
            del parser_used_fields[offset-1]
        return True

    def add_field(self, parsed_list, parsed_field):
        '''
        Ensures fields defined in parsed_field haven't been used before
        adding them to parsed_list.
        Called internally in _parse_kvfmt and _parse.
        '''
        start_field_id = parsed_field['field_id']
        repeats = parsed_field.get('repeat', 1)
        success = self._check_overlap(start_field_id, repeats)
        if not success:
            name = parsed_field.get('name')
            raise BadFormatString('Multiple definitions found for field {0}{1}{2}.'.format(
                start_field_id,
                '' if repeats == 1 else ' or {0} more fields after it'.format(repeats-1),
                '' if name is None else ' ({0})'.format(name)
            ))

        parsed_list.append(parsed_field)

#
# Helper functions for Wire
#
def _group_fields_by_number(decoded_raw):
    """
    Build an index for the fields decoded by _yield_fields_from_wire().
    Called internally in _decode_wire().
    """
    index = {}
    for decoded in decoded_raw:
        field_id = decoded['id']
        if field_id not in index:
            index[field_id] = []
        index[field_id].append(decoded)
    return index

def _concat_fields(fields):
    """
    Concatenate 2 fields with the same wire type together.
    Called internally in _decode_wire().
    """
    result_wire = io.BytesIO()
    result = {'id': fields[0]['id'], 'wire_type': fields[0]['wire_type']}
    for field in fields:
        assert field['id'] == result['id'] and \
            field['wire_type'] == result['wire_type'], \
            'field id or wire_type mismatch'
        result_wire.write(field['data'])
    result['data'] = result_wire.getvalue()
    return result

class Wire:
    # Field aliases
    _FIELD_ALIAS = {
        'v': TYPE_SINT, 'V': TYPE_UINT,
        'l': TYPE_SFIXED32, 'L': TYPE_FIXED32,
        'u': TYPE_STRING,
    }

    # wire type, # of repeat and field seek
    _T_FMT = re.compile(
        r"^(?:({0})|({1}))(\d*)(?:@(\d+))?".format(
            '|'.join(_TYPE_TO_WIRE_TYPE_MAP.keys()),
            '|'.join(_FIELD_ALIAS.keys())
        )
    )

    # Group 1: required/repeated/packed repeated, 2: nested struct begin
    _T_PREFIX = re.compile(r'^([\*\+#]?)(\[?)')

    # Used for field seek after [ in kvfmt mode or after ] in fmtstr mode
    _T_FIELD_SEEK = re.compile(r'^@(\d+)')

    # The default maximum length of a negative vint encoded in 2's complement (in bits)
    _VINT_MAX_BITS = 64

    # Logger
    logger = logging.getLogger('minipb.Wire')

    def __init__(self, fmt, vint_2sc_max_bits=None, allow_sparse_dict=False):
        self._vint_2sc_max_bits = 0
        self._vint_2sc_mask = 0
        self.allow_sparse_dict = allow_sparse_dict
        self.vint_2sc_max_bits = vint_2sc_max_bits or self._VINT_MAX_BITS

        if isinstance(fmt, str):
            self._fmt = self._parse_format_string(fmt)
            self._kv_fmt = False
            self._msg_cls = None
        elif is_message(fmt):
            self._fmt = self._parse_msg_class(fmt)
            self._kv_fmt = False
            self._msg_cls = fmt
        else:
            self._fmt = self._parse_kvfmt(fmt)
            self._kv_fmt = True
            self._msg_cls = None


    @property
    def vint_2sc_max_bits(self):
        """
        The maximum number of bits a signed 2's complement vint can contain.
        """
        return self._vint_2sc_max_bits

    @vint_2sc_max_bits.setter
    def vint_2sc_max_bits(self, bits):
        self._vint_2sc_max_bits = bits
        self._vint_2sc_mask = (1 << bits) - 1

    @property
    def kvfmt(self):
        """
        True if the object works in key-value format list (kvfmt) mode.
        """
        return self._kv_fmt

    @property
    def message_cls(self):
        """
        True if the object works in Message class mode.
        """
        return self._msg_cls

    def _parse_kvfmt(self, fmtlist):
        """
        Similar to _parse_format_string() but for key-value format lists.
        """
        t_fmt = self._T_FMT
        t_prefix = self._T_PREFIX
        t_field_seek = self._T_FIELD_SEEK
        parsed_list = []
        field_id = 1
        overlap_check = _OverlapCheck()

        for entry in fmtlist:
            name = entry[0]
            fmt = entry[1]
            parsed_field = {}
            parsed_field['name'] = name
            if isinstance(fmt, str):
                ptr = 0
                m_prefix = t_prefix.match(fmt)
                if m_prefix:
                    ptr += _get_length_of_match(m_prefix)

                    # handle field seek
                    if ptr != len(fmt):
                        m_field_seek = t_field_seek.match(fmt[ptr:])
                        if m_field_seek:
                            ptr += _get_length_of_match(m_field_seek)
                            field_id = int(m_field_seek.group(1))

                    parsed_field['prefix'] = m_prefix.group(1)
                    # check for optional nested structure start (required if the field is also repeated)
                    if m_prefix.group(2) and len(entry) > 2:
                        parsed_field['field_id'] = field_id
                        parsed_field['field_type'] = TYPE_BYTES
                        parsed_field['subcontent'] = self._parse_kvfmt(entry[2])
                        field_id += 1
                        overlap_check.add_field(parsed_list, parsed_field)
                        continue
                    elif m_prefix.group(2):
                        raise BadFormatString('Nested field type used without specifying field format.')
                m_fmt = t_fmt.match(fmt[ptr:])
                if m_fmt:
                    # format seek
                    if m_fmt.group(4):
                        field_id = int(m_fmt.group(4))
                    ptr += _get_length_of_match(m_fmt)
                    resolved_fmt_char = None
                    # fmt is an alias
                    if m_fmt.group(2):
                        resolved_fmt_char = m_fmt.group(2)
                        parsed_field['field_type'] = self._FIELD_ALIAS[m_fmt.group(2)]
                    # fmt is an actual field type
                    elif m_fmt.group(1):
                        resolved_fmt_char = m_fmt.group(1)
                        parsed_field['field_type'] = m_fmt.group(1)
                    parsed_field['field_id'] = field_id
                    # only skip type (`x') is allowed for copying in key-value mode
                    if m_fmt.group(3) and resolved_fmt_char == 'x':
                        repeats = int(m_fmt.group(3))
                        parsed_field['repeat'] = repeats
                        field_id += repeats
                    elif m_fmt.group(3):
                        raise BadFormatString('Field copying is not allowed in key-value format list.')
                    else:
                        field_id += 1
                else:
                    raise BadFormatString('Invalid type for field "{0}"'.format(name))
                if len(fmt) != ptr:
                    raise BadFormatString('Unrecognized fragment "{0}" in format string'.format(fmt[ptr:]))
            else:
                # Hard-code the empty prefix because we don't support copying
                parsed_field['prefix'] = ''
                parsed_field['field_id'] = field_id
                parsed_field['field_type'] = TYPE_BYTES
                parsed_field['subcontent'] = self._parse_kvfmt(fmt)
                field_id += 1
            overlap_check.add_field(parsed_list, parsed_field)

        return parsed_list

    def _parse_format_string(self, fmtstr):
        """
        Parse format string to something more machine readable.
        Called internally inside the class.
        Format of parsed format list:
            - field_id: The id (index) of the field.
            - field_type: Type of the field. (see the doc, _FIELD_WIRE_TYPE and _FIELD_ALIAS)
            - prefix: Prefix of the field. (required, repeated, packed-repeated) (EXCLUDES nested structures)
                      Needs to be an empty string when there's none.
            - subcontent: Optional. Used for nested structures. (field_type must be `a' when this is defined)
            - repeat: Optional. Copy this field specified number of times to consecutive indices.
        """
        def _match_brace(string, start_pos, pair='[]'):
            """Pairing brackets"""
            depth = 1
            if string[start_pos] != pair[0]:
                return None
            for index, char in enumerate(string[start_pos + 1:]):
                if char == pair[0]:
                    depth += 1
                elif char == pair[1]:
                    depth -= 1
                if depth == 0:
                    return start_pos + index + 1
            return None

        #----------------------------------------------------------------------

        t_fmt = self._T_FMT
        t_prefix = self._T_PREFIX
        t_field_seek = self._T_FIELD_SEEK

        ptr = 0
        # it seems that field id 0 is invalid
        field_id = 1
        length = len(fmtstr)
        parsed_list = []
        overlap_check = _OverlapCheck()

        while ptr < length:
            parsed = {}
            m_prefix = t_prefix.match(fmtstr[ptr:])
            if m_prefix:
                ptr += _get_length_of_match(m_prefix)
                parsed['prefix'] = m_prefix.group(1)

                # check if we have an embedded message
                if m_prefix.group(2):
                    brace_offset = _match_brace(fmtstr, ptr - 1)

                    # bracket not match
                    if not brace_offset:
                        raise BadFormatString(
                            'Unmatched brace on position {0}'.format(ptr)
                        )
                    parsed['field_type'] = TYPE_BYTES
                    parsed['subcontent'] = self._parse_format_string(
                        fmtstr[ptr:brace_offset]
                    )
                    ptr = brace_offset + 1

                    # handle field seek
                    m_field_seek = t_field_seek.match(fmtstr[ptr:])
                    if m_field_seek is not None:
                        ptr += _get_length_of_match(m_field_seek)
                        field_id = int(m_field_seek.group(1))

                    parsed['field_id'] = field_id
                    field_id += 1

                    overlap_check.add_field(parsed_list, parsed)
                    continue
            m_fmt = t_fmt.match(fmtstr[ptr:])
            if m_fmt:
                ptr += _get_length_of_match(m_fmt)

                # format seek
                if m_fmt.group(4):
                    field_id = int(m_fmt.group(4))

                # fmt is an alias
                if m_fmt.group(2):
                    parsed['field_type'] = self\
                        ._FIELD_ALIAS[m_fmt.group(2)]
                # fmt is an actual field type
                elif m_fmt.group(1):
                    parsed['field_type'] = m_fmt.group(1)

                # save field id
                parsed['field_id'] = field_id

                # check for type clones (e.g. `v3')
                if m_fmt.group(3):
                    parsed['repeat'] = int(m_fmt.group(3))
                    field_id += int(m_fmt.group(3))
                else:
                    parsed['repeat'] = 1
                    field_id += 1

                overlap_check.add_field(parsed_list, parsed)

            else:
                raise BadFormatString(
                    'Invalid token on position {0}'.format(ptr)
                )

        # all set
        return parsed_list

    def _parse_msg_class(self, msg_class):
        """
        Format of parsed format list:
        - field_id: The id (index) of the field.
        - field_type: Type of the field. (see the doc, _FIELD_WIRE_TYPE and _FIELD_ALIAS)
        - prefix: Prefix of the field. (required, repeated, packed-repeated) (EXCLUDES nested structures)
                    Needs to be an empty string when there's none.
        - subcontent: Optional. Used for nested structures. (field_type must be `a' when this is defined)
        - repeat: Optional. Copy this field specified number of times to consecutive indices.
        """
        parsed_list = []

        name_to_fields_map = getattr(msg_class, _MESSAGE_NAME_TO_FIELDS_MAP)
        for field_name, current_field_instance in name_to_fields_map.items():
            field_type = current_field_instance.type
            field_number = current_field_instance.number

            prefix = ''
            if current_field_instance.required:
                prefix = PREFIX_REQUIRED
            elif current_field_instance.repeated:
                prefix = PREFIX_REPEATED
            elif current_field_instance.repeated_packed:
                prefix = PREFIX_REPEATED_PACKED

            subcontent = None
            if is_message(field_type):
                subcontent = field_type
                field_type = TYPE_BYTES

            parsed_field = {}
            parsed_field['name'] = field_name
            parsed_field['field_id'] = field_number
            parsed_field['prefix'] = prefix
            parsed_field['field_type'] = field_type
            parsed_field['subcontent'] = subcontent # Set subcontent to the nested Message class
            parsed_list.append(parsed_field)

        return parsed_list

    def encode(self, *stuff):
        """
        Encode given objects to binary wire format.
        If the Wire object was created using the key-value format list,
        the method accepts one dict object that contains all the objects
        to be encoded.
        Otherwise, the method accepts multiple objects (like Struct.pack())
        and all objects will be encoded sequentially.
        """
        if self._kv_fmt or self._msg_cls:
            result = self._encode_wire(stuff[0])
        else:
            result = self._encode_wire(stuff)
        return result.getvalue()

    @classmethod
    def encode_raw(cls, stuff):
        return encode_raw(stuff)


    def _encode_wire(self, stuff, fmtable=None):
        """
        Encode a list to binary wire using fmtable
        Returns a BytesIO object (not a str)
        Used by the encode() method, may also be invoked by _encode_field()
        to encode nested structures
        """
        if fmtable == None:
            fmtable = self._fmt

        # Can be a index number or field name
        stuff_id = 0
        encoded = io.BytesIO()
        for fmt in fmtable:
            if self._kv_fmt or self._msg_cls:
                assert 'name' in fmt, 'Encoder is in key-value mode but name is undefined for this field'
                stuff_id = fmt['name']
            field_id_start = fmt['field_id']
            field_type = fmt['field_type']
            repeat = fmt.get('repeat', 1)
            for field_id in range(field_id_start, field_id_start + repeat):
                try:
                    if self._kv_fmt and self.allow_sparse_dict:
                        field_data = stuff.get(stuff_id)
                    elif self._msg_cls:
                        field_data = getattr(stuff, stuff_id)
                    else:
                        field_data = stuff[stuff_id]
                except (IndexError, KeyError) as e:
                    raise CodecError('Insufficient parameters '
                                        '(empty field {0} not padded with None)'.format(
                                            fmt['name'] if self._kv_fmt or self._msg_cls else field_id)) from e

                prefix = fmt['prefix']
                subcontent = fmt.get('subcontent')
                wire_type = _TYPE_TO_WIRE_TYPE_MAP[field_type]

                #self.logger.debug(
                #    '_encode_wire(): Encoding field #%d type %s prefix %s',
                #    field_id, field_type, prefix
                #)

                # Skip blank field (placeholder)
                if field_type == TYPE_EMPTY:
                    continue

                # Packed repeating field always has a str-like header
                if prefix == PREFIX_REPEATED_PACKED:
                    wire_type = _WIRE_TYPE_LEN

                encoded_header = _encode_header(wire_type, field_id)

                # Empty required field
                if prefix == PREFIX_REQUIRED and field_data == None:
                    raise CodecError('Required field cannot be None.')

                # Empty optional field
                if field_data == None:
                    if not self._kv_fmt and not self._msg_cls:
                        stuff_id += 1
                    continue

                # repeating field
                if prefix == PREFIX_REPEATED:
                    for obj in field_data:
                        encoded.write(encoded_header)
                        encoded.write(
                            self._encode_field(field_type, obj, subcontent)
                        )

                # packed repeating field
                elif prefix == PREFIX_REPEATED_PACKED:
                    packed_body = io.BytesIO()
                    for obj in field_data:
                        packed_body.write(self._encode_field(
                            field_type, obj, subcontent
                        ))
                    encoded.write(encoded_header)
                    encoded.write(_encode_bytes(packed_body.getvalue()))

                # normal field
                else:
                    encoded.write(encoded_header)
                    encoded.write(
                        self._encode_field(field_type, field_data, subcontent)
                    )
                if not self._kv_fmt and not self._msg_cls:
                    stuff_id += 1

        encoded.seek(0)
        return encoded

    def _encode_field(self, field_type, field_data, subcontent=None):
        """
        Encode a single field to binary wire format, without field_number and wire_type headers
        Called internally in _encode_wire() function
        """
        #self.logger.debug(
        #    '_encode_field(): pytype %s values %s',
        #    type(field_data).__name__, repr(field_data)
        #)

        field_encoded = None

        # nested
        if field_type == TYPE_BYTES and subcontent:
            if self._msg_cls:
                nested_msg_as_bytes = field_data.encode()
            else:
                nested_msg_as_bytes = self._encode_wire(field_data, subcontent).read()
            field_encoded = _encode_bytes(nested_msg_as_bytes)
        # everything else
        else:
            field_encoded = _encode_scalar_to_bytes(field_type, field_data, mask=self._vint_2sc_mask)

        return field_encoded


    def decode(self, data):
        """Decode given binary wire data to Python data types."""

        # Tested:
        #   types: z, T, a
        #   nested_structure
        #   repeated
        if not hasattr(data, 'read'):
            data = io.BytesIO(data)

        if self._kv_fmt:
            return dict(self._decode_wire(data))
        elif self._msg_cls:
            out_instance = self._msg_cls()
            for attr_name, value in self._decode_wire(data):
                setattr(out_instance, attr_name, value)
            return out_instance
        else:
            return tuple(self._decode_wire(data))

    @classmethod
    def decode_raw(cls, data):
        return decode_raw(data)

    def _decode_field(self, field_type, field_data, subcontent=None):
        """
        Decode a single field
        Called internally in _decode_wire() function
        """
        # check wire type
        wt_schema = _TYPE_TO_WIRE_TYPE_MAP[field_type]
        wt_data = field_data['wire_type']
        if wt_schema != wt_data:
            raise TypeError(
                'Wire type mismatch (expect {0} but got {1})'\
                    .format(wt_schema, wt_data)
            )

        field_decoded = None
        field_bytes = field_data['data']

        # the actual decoding process
        # nested structure
        if field_type == TYPE_BYTES and subcontent:
            if self._msg_cls:
                field_decoded = subcontent.decode(io.BytesIO(field_bytes))
            else:
                #self.logger.debug('_decode_field(): nested field begin')
                field_decoded = self._decode_wire(
                    io.BytesIO(field_bytes),
                    subcontent
                )
                if self._kv_fmt:
                    field_decoded = dict(field_decoded)
                else:
                    field_decoded = tuple(field_decoded)
                #self.logger.debug('_decode_field(): nested field end')
        else:
            field_decoded = _decode_scalar_from_bytes(field_type, field_bytes, max_bits=self._vint_2sc_max_bits, mask=self._vint_2sc_mask)

        return field_decoded

    def _decode_wire(self, buf, subfmt=None):
        """
        Apply schema, decode nested structure and fixed length data.
        Used by the decode() method, may also be invoked by _decode_field()
        to decode nested structures
        """
        decoded_raw_index = _group_fields_by_number(_yield_fields_from_wire(buf))
        if not subfmt:
            subfmt = self._fmt

        for fmt in subfmt:
            field_id_start = fmt['field_id']
            field_type = fmt['field_type']
            field_prefix = fmt.get('prefix')
            subcontent = fmt.get('subcontent')
            repeat = fmt.get('repeat', 1)

            # sanity check
            if self._kv_fmt or self._msg_cls:
                assert repeat == 1 or field_type == TYPE_EMPTY, 'Refuse to do field copying on non-skip field in key-value mode.'

            for field_id in range(field_id_start, field_id_start + repeat):
                #self.logger.debug(
                #    '_decode_wire(): processing field #%d type %s',
                #    field_id, field_type
                #)

                # skip blank field
                if field_type == TYPE_EMPTY:
                    continue

                # get all the data attached on the given field
                fields = decoded_raw_index.get(field_id)

                # handle empty fields
                if fields is None:
                    # raise error if a required field is empty
                    if field_prefix == PREFIX_REQUIRED:
                        raise CodecError(
                            'Field {0} is required but is empty'\
                                .format(field_id)
                        )
                    # otherwise, decode to None if field is empty
                    else:
                        field_decoded = None

                # identify which kind of repeated field is present
                # normal repeated fields
                elif field_prefix == PREFIX_REPEATED:
                    field_decoded = tuple(
                        self._decode_field(field_type, f, subcontent)
                        for f in fields
                    )

                # packed repeated field
                elif field_prefix == PREFIX_REPEATED_PACKED:
                    if len(fields) > 1:
                        self.logger.warning(
                            'Multiple data found in a packed-repeated field.'
                        )
                        fields = (_concat_fields(fields), )
                    if fields[0]['wire_type'] != _WIRE_TYPE_LEN:
                        raise CodecError('Packed repeated field {0} has wire type other than str'.format(
                            fmt['name'] if self._kv_fmt or self._msg_cls else field_id
                        ))
                    field = io.BytesIO(fields[0]['data'])
                    unpacked_field = _yield_fields_from_wire(
                        field,
                        wire_type=_TYPE_TO_WIRE_TYPE_MAP[field_type],
                        field_number=field_id
                    )
                    field_decoded = tuple(
                        self._decode_field(field_type, f, subcontent)
                        for f in unpacked_field
                    )

                # not a repeated field but has multiple data in one field
                elif len(fields) > 1:
                    self.logger.warning(
                        'Multiple data found in a non-repeated field.'
                    )
                    # Check if we are expecting a nested message
                    if subcontent is None:
                        # Use the last found data
                        field_decoded = self._decode_field(
                            field_type, fields[-1], subcontent
                        )
                    else:
                        # Concat all pieces of the nested message together and decode
                        #
                        # https://developers.google.com/protocol-buffers/docs/encoding#optional
                        # For embedded message fields, the parser merges multiple instances of the same field,
                        # as if with the `Message::MergeFrom` method – that is, all singular scalar fields in
                        # the latter instance replace those in the former, singular embedded messages are merged,
                        # and repeated fields are concatenated.
                        field_decoded = self._decode_field(
                            field_type, _concat_fields(fields), subcontent
                        )

                # not a repeated field
                else:
                    field_decoded = self._decode_field(
                        field_type, fields[0], subcontent
                    )

                if self._kv_fmt or self._msg_cls:
                    yield fmt['name'], field_decoded
                else:
                    yield field_decoded

#
# Defining schema's using Message and Field classes
#
_MESSAGE_NAME_TO_FIELDS_MAP = '_minipb_name_to_fields_map'
_MESSAGE_NUMBER_TO_FIELDS_MAP = '_minipb_number_to_fields_map'
_MESSAGE_WIRE = '_minipb_wire'

# https://protobuf.dev/programming-guides/proto3/#assigning-field-numbers
MIN_FIELD_NUMBER = 1
MAX_FIELD_NUMBER = 2**29 - 1

MIN_RESERVED_BY_PROTOBUF_FIELD_NUMBER = 19000
MAX_RESERVED_BY_PROTOBUF_FIELD_NUMBER = 19999

class Field:
    """MiniPB Field inspired from dataclasses module
    https://github.com/python/cpython/blob/3.11/Lib/dataclasses.py#L273
    """
    __slots__ = ('name', 'number', 'type', 'required', 'repeated', 'repeated_packed')

    def __init__(self, number, type_, required=False, repeated=False, repeated_packed=False):
        assert MIN_FIELD_NUMBER <= number <= MAX_FIELD_NUMBER, \
            'Field number out of bounds, not between {} and {}'.format(MIN_FIELD_NUMBER, MAX_FIELD_NUMBER)

        assert not (MIN_RESERVED_BY_PROTOBUF_FIELD_NUMBER <= number <= MAX_RESERVED_BY_PROTOBUF_FIELD_NUMBER), \
            'Field number in Protocol Buffer reserved range of {} to {}'.format(
            MIN_RESERVED_BY_PROTOBUF_FIELD_NUMBER, MAX_RESERVED_BY_PROTOBUF_FIELD_NUMBER)

        assert type_ in TYPES or issubclass(type_, Message)

        assert sum([required, repeated, repeated_packed]) <= 1, "Can only speciffy 1 of required, repeated or repeated_Packed"
        self.name = None     # NOTE: Set after the fact by @process_message_fields
        self.number = number
        self.type = type_

        self.required = required
        self.repeated = repeated
        self.repeated_packed = repeated_packed

def process_message_fields(cls):
    # Identify all Fields
    name_to_fields_map = collections.OrderedDict()

    # Get Fields from base classes
    for current_base in cls.__bases__:
        # Only process classes that have been processed by our
        # decorator.  That is, they have a _FIELDS attribute.
        base_fields_map = getattr(current_base, _MESSAGE_NAME_TO_FIELDS_MAP, None)
        if not base_fields_map:
            continue

        for attr_name, current_field in base_fields_map.items():
            name_to_fields_map[attr_name] = current_field

    # Get Fields from this class declaration
    number_to_fields_map = dict()
    for attr_name, current_field in cls.__dict__.items():
        if not isinstance(current_field, Field):
            continue

        # Splice in Field name since Field declaration didn't have this
        current_field.name = attr_name
        number_to_fields_map[current_field.number] = current_field

    # Sort by Field Number
    for _, current_field in sorted(number_to_fields_map.items()):
        name_to_fields_map[current_field.name] = current_field

    # Add in Message.Fields
    setattr(cls, _MESSAGE_NAME_TO_FIELDS_MAP, name_to_fields_map)
    setattr(cls, _MESSAGE_NUMBER_TO_FIELDS_MAP, number_to_fields_map)
    return cls

def is_message(obj):
    """Returns True if obj is a dataclass or an instance of a
    dataclass."""
    cls = obj if isinstance(obj, type) else type(obj)
    return hasattr(cls, _MESSAGE_NAME_TO_FIELDS_MAP)

def _msg_inner_to_dict(in_value):
    if type(in_value) in (list, tuple):
        return tuple(_msg_inner_to_dict(current_value) for current_value in in_value)
    elif is_message(in_value):
        return in_value.to_dict()
    return in_value

def _msg_inner_from_dict(in_value, current_field):
    field_type = current_field.type
    if type(in_value) in (list, tuple):
        return tuple(_msg_inner_from_dict(current_value, current_field) for current_value in in_value)
    elif is_message(field_type):
        return field_type.from_dict(in_value)
    return in_value

class Message:
    _minipb_name_to_fields_map   = None # collections.OrderedDict
    _minipb_number_to_fields_map = None # dict
    _minipb_wire                 = None # Wire

    def __init__(self, **kwargs):
        name_to_fields_map = getattr(self, _MESSAGE_NAME_TO_FIELDS_MAP)
        assert name_to_fields_map is not None, "Missing self.{}, forget to decorate Message with @process_message_fields?".format(_MESSAGE_NAME_TO_FIELDS_MAP)
        for current_attr, current_field in name_to_fields_map.items():
            value = kwargs.get(current_attr, None)
            if current_field.repeated or current_field.repeated_packed:
                value = value or list()

            setattr(self, current_attr, value)

    def __repr__(self):
        keys = getattr(self, _MESSAGE_NAME_TO_FIELDS_MAP).keys()
        return '{0}({1})'.format(
            type(self).__name__,
            ', '.join('{0}={1}'.format(key, repr(getattr(self, key))) for key in keys)
        )

    def __eq__(self, other):
        if other is None:
            return False

        if other.__class__ is not self.__class__:
            raise NotImplementedError('{} != {}'.format(other.__class__, self.__class__))

        for current_attr in getattr(self, _MESSAGE_NAME_TO_FIELDS_MAP).keys():
            if getattr(self, current_attr) != getattr(other, current_attr):
                return False

        return True

    def to_dict(self, dict_factory=collections.OrderedDict):
        output_map = dict_factory()
        for attr_name in getattr(self, _MESSAGE_NAME_TO_FIELDS_MAP).keys():
            # Get the value on this instance
            in_value = getattr(self, attr_name)
            out_value = _msg_inner_to_dict(in_value)
            output_map[attr_name] = out_value
        return output_map

    def encode(self):
        return self.wire().encode(self)

    @classmethod
    def from_dict(cls, in_dict):
        name_to_fields_map = getattr(cls, _MESSAGE_NAME_TO_FIELDS_MAP)

        out_instance = cls()
        for attr_name, current_field in name_to_fields_map.items():
            in_value = in_dict[attr_name]
            out_value = _msg_inner_from_dict(in_value, current_field)
            setattr(out_instance, attr_name, out_value)

        return out_instance

    @classmethod
    def decode(cls, in_bytes):
        decoded_msg = cls.wire().decode(in_bytes)
        return decoded_msg

    @classmethod
    def wire(cls):
        existing_wire = getattr(cls, _MESSAGE_WIRE, None)
        if not existing_wire:
            existing_wire = Wire(cls)
            setattr(cls, _MESSAGE_WIRE, existing_wire)
        return existing_wire

def encode(fmtstr, *stuff):
    """Encode given Python object(s) to binary wire using fmtstr"""
    return Wire(fmtstr).encode(*stuff)

def decode(fmtstr, data):
    """Decode given binary wire to Python object(s) using fmtstr"""
    return Wire(fmtstr).decode(data)


if __name__ == '__main__':
    import sys
    import json
    logging.basicConfig()
    def usage():
        """Isn't that obvious?"""
        print('Usage: {prog} <-d|-e> <fmtstr>'.format(prog=sys.argv[0]))
        sys.exit(1)

    if len(sys.argv) < 3:
        usage()
    if sys.argv[1] == '-d':
        json.dump(decode(sys.argv[2], sys.stdin.buffer), sys.stdout)
        sys.stdout.write("\n")
    elif sys.argv[1] == '-e':
        sys.stdout.buffer.write(encode(sys.argv[2], *json.load(sys.stdin)))
    else:
        usage()
