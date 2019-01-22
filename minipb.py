###############################################################################
#
# minipb.py
#
# SPDX-License-Identifier: LGPL-3.0+
#

"""
minipb - A simple codec module for the binary wire format shipped with
         Google's Protobuf protocol library

minipb uses format strings with struct-like syntax to encode/decode data
between Python data types and Protobuf binary wire data.
Compare to original Protobuf, it is more light-weight, simple and therefore
can be used in prototyping and reverse-engineering.
"""


import logging
import re
import struct
from collections import namedtuple
import io

__all__ = [
    'BadFormatString', 'CodecError',
    'Wire', 'RawWire',
    'encode', 'decode'
]

class BadFormatString(Exception): pass
class CodecError(Exception): pass

class Wire(object):
    # Field types
    FIELD_WIRE_TYPE = {
        'x': None,
        'i': 5, 'I': 5, 'q': 1, 'Q': 1, 'f': 5, 'd': 1,
        'a': 2, 'b': 0, 'z': 0, 't': 0, 'T': 0, 'U': 2,
    }
    # Field aliases
    FIELD_ALIAS = {
        'v': 'z', 'V': 'T',
        'l': 'q', 'L': 'Q'
    }

    # The maximum length of a negative vint encoded in 2's complement (in bits)
    VINT_MAX_BITS = 64

    def __init__(self, fmtstr, loglevel=logging.WARNING):
        self._fmt = self._parse(fmtstr)
        self.logger = logging.getLogger('minipb.Wire')
        self.loglevel = loglevel

    @property
    def loglevel(self):
        return self.logger.getEffectiveLevel()

    @loglevel.setter
    def loglevel(self, level):
        self._loglevel = level
        self.logger.setLevel(level)

    def _parse(self, fmtstr):
        """
        Parse format string to something more machine readable.
        Called internally inside the class.
        """
        def __match_brace(string, start_pos, pair='[]'):
            """Pairing brackets (used internally in _parse method)"""
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

        t_fmt = re.compile(
            r"^(?:({0})|({1}))(\d*)".format(
                '|'.join(self.__class__.FIELD_WIRE_TYPE.keys()),
                '|'.join(self.__class__.FIELD_ALIAS.keys())
            )
        ) # wire type & # of repeat
        t_prefix = re.compile(r'^([\*\+#]?)(\[?)') # 1: m/rf/prf 2: nested?

        ptr = 0
        # it seems that field id 0 is invalid
        field_id = 1
        length = len(fmtstr)
        parsed_list = []

        while ptr < length:
            parsed = {}
            m_prefix = t_prefix.match(fmtstr[ptr:])
            if m_prefix:
                ptr += m_prefix.end()
                parsed['prefix'] = m_prefix.group(1)

                # check if we have a nested structure
                if m_prefix.group(2):
                    brace_offset = __match_brace(fmtstr, ptr - 1)

                    # bracket not match
                    if not brace_offset:
                        raise BadFormatString(
                            'Unmatched brace on position {0}'.format(ptr)
                        )
                    parsed['field_id'] = field_id
                    parsed['field_type'] = 'a'
                    parsed['subcontent'] = self._parse(
                        fmtstr[ptr:brace_offset]
                    )
                    ptr = brace_offset + 1
                    field_id += 1

                    parsed_list.append(parsed)
                    continue
            m_fmt = t_fmt.match(fmtstr[ptr:])
            if m_fmt:
                ptr += m_fmt.end()

                # fmt is an alias
                if m_fmt.group(2):
                    parsed['field_type'] = self.__class__\
                        .FIELD_ALIAS[m_fmt.group(2)]
                # fmt is an actual field type
                elif m_fmt.group(1):
                    parsed['field_type'] = m_fmt.group(1)

                parsed['field_id'] = field_id
                if m_fmt.group(3):
                    parsed['repeat'] = int(m_fmt.group(3))
                    field_id += int(m_fmt.group(3))
                else:
                    parsed['repeat'] = 1
                    field_id += 1

                parsed_list.append(parsed)

            else:
                raise BadFormatString(
                    'Invalid token on position {0}'.format(ptr)
                )

        # all set
        return parsed_list

    def encode(self, *stuff):
        """Encode given objects to binary wire format."""

        # Tested:
        #   types: T, a
        #   nested_structure

        result = self.encode_wire(stuff)
        return result.getvalue()
        
    def encode_wire(self, stuff, fmtable = None):
        """
        Encode a list to binary wire using fmtable
        Returns a BytesIO object (not a str)
        Used by the encode() method, may also be invoked by encode_field()
        to encode nested structures
        """
        if fmtable == None:
            fmtable = self._fmt

        stuff_id = 0
        encoded = io.BytesIO()
        for fmt in fmtable:
            field_id_start = fmt['field_id']
            field_type = fmt['field_type']
            repeat = fmt.get('repeat', 1)
            for field_id in range(field_id_start, field_id_start + repeat):
                try:
                    field_data = stuff[stuff_id]
                except IndexError:
                    raise CodecError('Insufficient parameters '
                                     '(empty fields not padded with None)')
                prefix = fmt['prefix']
                subcontent = fmt.get('subcontent')
                wire_type = self.__class__.FIELD_WIRE_TYPE[fmt['field_type']]

                self.logger.debug(
                    'encode_wire(): Encoding field #%d type %s prefix %s',
                    field_id, field_type, prefix
                )

                # Skip blank field (placeholder)
                if field_type == 'x':
                    continue

                # Packed repeating field always has a str-like header
                if prefix == '#':
                    encoded_header = self.encode_header(
                        self.__class__.FIELD_WIRE_TYPE['a'],
                        field_id
                    )
                else:
                    encoded_header = self.encode_header(wire_type, field_id)

                # Empty required field
                if prefix == '*' and field_data == None:
                    raise CodecError('Required field cannot be None.')

                # Empty optional field
                if field_data == None:
                    stuff_id += 1
                    continue

                # repeating field
                if prefix == '+':
                    for obj in field_data:
                        encoded.write(encoded_header)
                        encoded.write(
                            self.encode_field(field_type, obj, subcontent)
                        )

                # packed repeating field
                elif prefix == '#':
                    packed_body = io.BytesIO()
                    for obj in field_data:
                        packed_body.write(self.encode_field(
                            field_type, obj, subcontent
                        ))
                    encoded.write(encoded_header)
                    encoded.write(self.encode_str(packed_body.getvalue()))

                # normal field
                else:
                    encoded.write(encoded_header)
                    encoded.write(
                        self.encode_field(field_type, field_data, subcontent)
                    )

                stuff_id += 1

        encoded.seek(0)
        return encoded

    def encode_field(self, field_type, field_data, subcontent=None):
        """
        Encode a single field to binary wire format
        Called internally in encode_wire() function
        """
        self.logger.debug(
            'encode_field(): pytype %s values %s', 
            type(field_data).__name__, repr(field_data)
        )

        field_encoded = None

        # nested
        if field_type == 'a' and subcontent:
            field_encoded = self.encode_str(
                self.encode_wire(field_data, subcontent).read()
            )
        # bytes
        elif field_type == 'a':
            field_encoded = self.encode_str(field_data)

        # strings
        elif field_type == 'U':
            field_encoded = self.encode_str(field_data.encode('utf-8'))

        # vint family (signed, unsigned and boolean)
        elif field_type in 'Ttzb':
            if field_type == 't':
                field_data = self.vint_2sc(field_data)
            elif field_type == 'z':
                field_data = self.vint_zigzagify(field_data)
            elif field_type == 'b':
                field_data = int(field_data)
            field_encoded = self.encode_vint(field_data)

        # fixed numerical value
        elif field_type in 'iIqQfd':
            field_encoded = struct.pack(
                '<{0}'.format(field_type), field_data
            )

        return field_encoded

    def encode_header(self, f_type, f_id):
        """
        Encode a header
        Called internally in encode_wire() function
        """
        return struct.pack('B', ((f_id << 3) | f_type) & 255)

    def vint_zigzagify(self, number):
        """
        Perform zigzag encoding
        Called internally in encode_field() function
        """
        num = number << 1
        if number < 0:
            num = ~num
        return num

    def vint_2sc(self, number, bits=32):
        """
        Perform Two's Complement encoding
        Called internally in encode_field() function
        """
        bits = number.bit_length()
        return number & (1 << (bits + 1)) - 1

    def encode_vint(self, number):
        """
        Encode a number to vint (Wire Type 0).
        Numbers can only be signed or unsigned. Any number less than 0 must
        be processed either using zigzag or 2's complement (2sc) before
        passing to this function.
        Called internally in encode_field() function
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

    def encode_str(self, string):
        """
        Encode a string/binary stream into protobuf variable length by
        appending a special header containing the length of the string.
        Called internally in encode_field() function
        """
        result = self.encode_vint(len(string))
        result += string
        return result

    def decode(self, data):
        """Decode given binary wire data to Python data types."""

        # Tested:
        #   types: z, T, a
        #   nested_structure
        #   repeated
        if not hasattr(data, 'read'):
            data = io.BytesIO(data)

        return tuple(self.decode_wire(data))

    def decode_header(self, data):
        """
        Decode field header.
        Called internally in decode() method
        """
        ord_data = struct.unpack('B', data)[0]
        f_type = ord_data & 7
        f_id = ord_data >> 3
        return f_type, f_id

    def decode_vint(self, buf):
        """
        Decode vint encoded integer.
        Called internally in decode() method
        """
        ctr = 0
        result = 0
        while 1:
            tmp = struct.unpack('B', buf.read(1))[0]
            result |= (tmp & 0x7f) << (7 * ctr)
            if not (tmp >> 7): break
            ctr += 1
        return result

    def vint_dezigzagify(self, number):
        """
        Convert zigzag encoded integer to its original form.
        Called internally in decode_field() function
        """

        assert number >= 0, 'number is less than 0'
        is_neg = number & 1
        num = number >> 1
        if is_neg:
            num = ~num
        return num

    def vint_2sctosigned(self, number):
        """
        Decode Two's Complement encoded integer (which were treated by the
        'shallow' decoder as unsigned vint earlier) to normal signed integer
        Called internally in decode_field() function
        """
        assert number >= 0, 'number is less than 0'
        if (number >> (self.__class__.VINT_MAX_BITS - 1)) & 1:
            number = ~(~number & ((1 << self.__class__.VINT_MAX_BITS) - 1))
        return number

    def decode_str(self, buf):
        """
        Decode Protobuf variable length to Python string
        Called internally in decode_field() function
        """
        length = self.decode_vint(buf)
        return buf.read(length)

    def _break_down(self, buf, type_override=None, id_override=None):
        """
        Helper method to 'break down' a wire string into a list for
        further processing.
        Pass type_override and id_override to decompose headerless wire
        strings. (Mainly used for unpacking packed repeated fields)
        Called internally in decode_wire() function
        """
        if type_override is not None:
            assert id_override is not None,\
                'Field ID must be specified in headerless mode'
            buf_length = len(buf.getvalue())

        while 1:
            field = {}
            if type_override is not None:
                if buf_length <= buf.tell():
                    break
                f_type = type_override
                f_id = id_override
            else:
                tmp = buf.read(1)
                if not tmp: break
                f_type, f_id = self.decode_header(tmp)

            self.logger.debug(
                "_break_down():field #%d pbtype #%d", f_id, f_type
            )
            if f_type == 0: # vint
                field['data'] = self.decode_vint(buf)
            elif f_type == 1: # 64-bit
                field['data'] = buf.read(8)
            elif f_type == 2: # str
                field['data'] = self.decode_str(buf)
            elif f_type == 5: # 32-bit
                field['data'] = buf.read(4)
            else:
                self.logger.warning(
                    "_break_down():Ignore unknown type #%d", f_type
                )
                continue
            field['id'] = f_id
            field['wire_type'] = f_type
            yield field

    def decode_field(self, field_type, field_data, subcontent=None):
        """
        Decode a single field
        Called internally in decode_wire() function
        """
        # check wire type
        wt_schema = self.__class__.FIELD_WIRE_TYPE[field_type]
        wt_data = field_data['wire_type']
        if wt_schema != wt_data:
            raise TypeError(
                'Wire type mismatch (expect {0} but got {1})'\
                    .format(wt_schema, wt_data)
            )

        field_decoded = None

        # the actual decoding process
        # nested structure
        if field_type == 'a' and subcontent:
            self.logger.debug('decode_field(): nested field begin')
            field_decoded = tuple(self.decode_wire(
                io.BytesIO(field_data['data']),
                subcontent
            ))
            self.logger.debug('decode_field(): nested field end')

        # string, unsigned vint (2sc)
        elif field_type in 'aT':
            field_decoded = field_data['data']

        # unicode
        elif field_type in 'U':
            field_decoded = field_data['data'].decode('utf-8')

        # vint (zigzag)
        elif field_type == 'z':
            field_decoded = self.vint_dezigzagify(field_data['data'])

        # signed 2sc
        elif field_type == 't':
            field_decoded = self.vint_2sctosigned(field_data['data'])

        # fixed, float, double
        elif field_type in 'iIfdqQ':
            field_decoded = struct.unpack(
                '<{0}'.format(field_type), field_data['data']
            )[0]

        # boolean
        elif field_type == 'b':
            if field_data['data'] == 0:
                field_decoded = False
            else:
                field_decoded = True

        return field_decoded

    def decode_wire(self, buf, subfmt=None):
        """
        Apply schema, decode nested structure and fixed length data.
        Used by the decode() method, may also be invoked by decode_field()
        to decode nested structures
        """
        def _concat_fields(fields):
            """
            Concatenate 2 fields with the same wire type together
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

        decoded_raw = tuple(self._break_down(buf))
        if not subfmt:
            subfmt = self._fmt

        for fmt in subfmt:
            field_id_start = fmt['field_id']
            field_type = fmt['field_type']
            field_prefix = fmt.get('prefix')
            subcontent = fmt.get('subcontent')
            repeat = fmt.get('repeat', 1)

            for field_id in range(field_id_start, field_id_start + repeat):
                self.logger.debug(
                    'decode_wire(): processing field #%d type %s',
                        field_id, field_type
                )

                # skip blank field
                if field_type == 'x':
                    continue

                # get all the data attached on the given field
                fields = tuple(x for x in decoded_raw if x['id'] == field_id)

                # raise error if a required field is empty
                if field_prefix == '*' and len(fields) == 0:
                    raise CodecError(
                        'Field {0} is required but is empty'\
                            .format(field_id)
                    )

                # identify which kind of repeated field is present
                # normal repeated fields
                if field_prefix == '+':
                    field_decoded = tuple(
                        self.decode_field(field_type, f, subcontent)
                        for f in fields
                    )

                # packed repeated field
                elif field_prefix == '#':
                    if len(fields) > 1:
                        self.logger.warning(
                            'Multiple data found in a packed-repeated field.'
                        )
                        fields = tuple(_concat_fields(fields))
                    assert fields[0]['wire_type'] == \
                        self.__class__.FIELD_WIRE_TYPE['a'], \
                        'Packed repeating field has wire type other than str'
                    field = io.BytesIO(fields[0]['data'])
                    unpacked_field = self._break_down(
                        field,
                        type_override = self.__class__.FIELD_WIRE_TYPE[field_type],
                        id_override = field_id
                    )
                    field_decoded = tuple(
                        self.decode_field(field_type, f, subcontent)
                        for f in unpacked_field
                    )


                # not a repeated field but has multiple data in one field
                elif len(fields) > 1:
                    self.logger.warning(
                        'Multiple data found in a non-repeated field.'
                    )
                    if subcontent is None:
                        field_decoded = self.decode_field(
                            field_type, fields[-1], subcontent
                        )
                    else:
                        field_decoded = self.decode_field(
                            field_type, _concat_fields(fields), subcontent
                        )
                # not a repeated field
                else:
                    if len(fields) != 0:
                        field_decoded = self.decode_field(
                            field_type, fields[0], subcontent
                        )
                    else:
                        field_decoded = None

                yield field_decoded


class RawWire(Wire):
    '''
    This class exposes the internal encoding/decoding routines of the Wire class
    to allow raw wire data generating/parsing without the need of a schema
    It is useful for analyzing Protobuf messages with an unknown schema
    '''
    def __init__(self, loglevel=logging.WARNING):
        self.logger = logging.getLogger('minipb.RawWire')
        self.loglevel = loglevel

    def decode(self, data):
        '''
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
        '''
        if not hasattr(data, 'read'):
            data = io.BytesIO(data)

        return tuple(self._break_down(data))

    def encode(self, stuff):
        '''
        Encode the output of decode() back to binary wire format
        '''
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

        ENCODERS = {
            0: self.encode_vint,
            1: lambda n: _check_bytes_length(n, 8),
            2: self.encode_str,
            5: lambda n: _check_bytes_length(n, 4)
        }
        encoded = io.BytesIO()
        for s in stuff:
            encoded.write(self.encode_header(s['wire_type'], s['id']))
            if s['wire_type'] not in ENCODERS.keys():
                raise ValueError('Unknown type {}'.format(s['wire_type']))
            encoded.write(ENCODERS[s['wire_type']](s['data']))

        return encoded.getvalue()


def encode(fmtstr, *stuff):
    """Encode given Python object(s) to binary wire using fmtstr"""
    return Wire(fmtstr).encode(*stuff)

def decode(fmtstr, data):
    """Decode given binary wire to Python object(s) using fmtstr"""
    return Wire(fmtstr).decode(data)

def encode_raw(objs):
    """
    Encode a list of raw data and types to binary wire format
    Useful for analyzing Protobuf messages with unknown schema
    """
    return RawWire().encode(objs)

def decode_raw(data):
    """
    Decode given binary wire to a list of raw data and types
    Useful for analyzing Protobuf messages with unknown schema
    """
    return RawWire().decode(data)

if __name__ == '__main__':
    import sys
    import json
    logging.basicConfig()
    def usage():
        """Isn't that obvious?"""
        print('Usage: {prog} <-d|-e> <fmtstr>'.format(prog = sys.argv[0]))
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
