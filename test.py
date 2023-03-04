#!/usr/bin/env python3
import unittest
import minipb

TEST_RAW_ENCODED = b'\x08\x7b\x12\x04\x74\x65\x73\x74\x1a\x0b\x0a\x06\x73\x74\x72\x69\x6e\x67\x10\xf8\x06\x1a\x13\x0a\x0e\x61\x6e\x6f\x74\x68\x65\x72\x5f\x73\x74\x72\x69\x6e\x67\x10\xb9\x60'

TEST_RAW_DECODED = ({'data': 123, 'id': 1, 'wire_type': 0}, {'data': b'test', 'id': 2, 'wire_type': 2}, {'data': b'\n\x06string\x10\xf8\x06', 'id': 3, 'wire_type': 2}, {'data': b'\n\x0eanother_string\x10\xb9`', 'id': 3, 'wire_type': 2})

TEST_FIELD_SEEK_SIMPLE = b'\x10\x01\x18\x02R\x05test1\xa2\x01\x05test2'

TEST_FIELD_SEEK_COMPLEX = b'\xa2\x01\t\x08\x02R\x05hello\xf2\x01\x06\x12\x04str1\xf2\x01\x06\x12\x04str2'

class TestMiniPB(unittest.TestCase):
    # some of the following data were taken from
    # https://developers.google.com/protocol-buffers/docs/encoding
    def test_codec_vint(self):
        '''
        Codec: vint.
        '''
        expected_pb = b'\x08\x96\x01'
        raw_obj = 150
        self.assertEqual(minipb.encode('V', raw_obj), expected_pb)
        self.assertEqual(minipb.decode('V', expected_pb)[0], raw_obj)

    def test_codec_str(self):
        '''
        Codec: string.
        '''
        expected_pb = b'\x12\x07\x74\x65\x73\x74\x69\x6e\x67'
        raw_obj = 'testing'
        self.assertEqual(minipb.encode('xU', raw_obj), expected_pb)
        self.assertEqual(minipb.decode('xU', expected_pb)[0], raw_obj)

    def test_codec_packed_repeated_field(self):
        '''
        Codec: Packed repeated field.
        '''
        expected_pb = b'\x22\x06\x03\x8e\x02\x9e\xa7\x05'
        raw_obj = (3, 270, 86942)
        self.assertEqual(minipb.encode('x3#V', raw_obj), expected_pb)
        self.assertEqual(minipb.decode('x3#V', expected_pb)[0], raw_obj)

    def test_codec_packed_repeated_field_double_decode(self):
        '''
        Codec: Packed repeated field concatenation.
        '''
        expected_pb = b'\x22\x06\x03\x8e\x02\x9e\xa7\x05' * 2
        raw_obj = (3, 270, 86942) * 2
        self.assertEqual(minipb.decode('x3#V', expected_pb)[0], raw_obj)

    def test_codec_nested_message(self):
        '''
        Codec: Nested message.
        '''
        expected_pb = b'\x1a\x03\x08\x96\x01'
        raw_obj = (150, )
        self.assertEqual(minipb.encode('x2[V]', raw_obj), expected_pb)
        self.assertEqual(minipb.decode('x2[V]', expected_pb)[0], raw_obj)

    def test_codec_fixed(self):
        '''
        Codec: Fixed types.
        '''
        expected_pb = b'\r\xff\xff\xff\xff\x15\x01\x00\x00\x00\x1d\x00\x00\x80?!\xcc\xe3# \xfd\xff\xff\xff)\xd2\x02\x96I\x00\x00\x00\x001\x18-DT\xfb!\t@'
        fields = (-1, 1, 1.0, -12345678900, 1234567890, 3.141592653589793)
        self.assertEqual(minipb.encode('iIfqQd', *fields), expected_pb)
        self.assertEqual(minipb.decode('iIfqQd', expected_pb), fields)

    def test_codec_vint_field(self):
        '''
        Codec: Longer than 1 byte field ID.
        '''
        expected_pb = b'\x80\x01\x01'
        fields = (1,)
        # Field 16 requires 2 bytes
        self.assertEqual(minipb.encode('x15V', *fields), expected_pb)
        self.assertEqual(minipb.decode('x15V', expected_pb), fields)

    def test_codec_vint_2sc_negative(self):
        '''
        Codec: Negative 2's complement vint using default vint_2sc_max_bits.
        '''
        expected_pb = b'\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01'
        fields = (-1,)
        self.assertEqual(minipb.encode('t', *fields), expected_pb)
        self.assertEqual(minipb.decode('t', expected_pb), fields)

    def test_codec_vint_2sc_negative_force_32(self):
        '''
        Codec: Negative 2's complement vint using vint_2sc_max_bits=32.
        '''
        expected_pb = b'\x08\xff\xff\xff\xff\x0f'
        fields = (-1,)
        w = minipb.Wire('t')
        w.vint_2sc_max_bits = 32
        self.assertEqual(w.encode(*fields), expected_pb)
        self.assertEqual(w.decode(expected_pb), fields)

    def test_kvfmt_single(self):
        '''
        Key-value format list: Single field.
        '''
        expected_pb = b'\x08\x96\x01'
        raw_obj = {'value': 150}
        schema = (('value', 'V'),)
        w = minipb.Wire(schema)
        self.assertEqual(w.encode(raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), raw_obj)

    def test_kvfmt_complex(self):
        '''
        Key-value format list: Complex message.
        '''
        expected_pb = b'\x08\x7b\x12\x04\x74\x65\x73\x74\x1a\x0b\x0a\x06\x73\x74\x72\x69\x6e\x67\x10\xf8\x06'
        raw_obj = {
            'number': 123,
            'string': 'test',
            'nested': {
                'str2': 'string',
                'num2': 888,
            }
        }
        schema = (
            ('number', 'V'),
            ('string', 'U'),
            ('nested', (('str2', 'U'),
                        ('num2', 'V'),)),
        )
        w = minipb.Wire(schema)
        self.assertEqual(w.encode(raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), raw_obj)

    def test_kvfmt_very_complex(self):
        '''
        Key-value format list: Very complex message.
        '''
        expected_pb = b'\x08\x7b\x12\x04\x74\x65\x73\x74\x1a\x0b\x0a\x06\x73\x74\x72\x69\x6e\x67\x10\xf8\x06\x1a\x13\x0a\x0e\x61\x6e\x6f\x74\x68\x65\x72\x5f\x73\x74\x72\x69\x6e\x67\x10\xb9\x60'
        raw_obj = {
            'number': 123,
            'string': 'test',
            'nested': (
                {
                    'str2': 'string',
                    'num2': 888,
                }, {
                    'str2': 'another_string',
                    'num2': 12345,
                },
            ),
        }
        schema = (
            ('number', 'V'),
            ('string', 'U'),
            ('nested', '+[', (('str2', 'U'),
                              ('num2', 'V'),)),
        )
        w = minipb.Wire(schema)
        self.assertEqual(w.encode(raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), raw_obj)

    def test_kvfmt_sparse(self):
        '''
        Key-value format list: Sparse input with allow_sparse_dict=True.
        '''
        expected_pb = b'\x08\x96\x01'
        raw_obj = {'value': 150}
        expected_obj = raw_obj.copy()
        expected_obj['value2'] = None

        schema = (('value', 'V'), ('value2', 'V'),)
        w = minipb.Wire(schema, allow_sparse_dict=True)
        self.assertEqual(w.encode(raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), expected_obj)

    def test_raw_encode(self):
        '''
        Raw: Encode.
        '''
        result = minipb.Wire.encode_raw(TEST_RAW_DECODED)
        self.assertEqual(result, TEST_RAW_ENCODED)

    def test_raw_decode(self):
        '''
        Raw: Decode.
        '''
        result = minipb.Wire.decode_raw(TEST_RAW_ENCODED)
        self.assertTupleEqual(result, TEST_RAW_DECODED)

    def test_field_seek_fmtstr_simple(self):
        '''
        Field seek with format string: simple.
        '''
        expected_pb = TEST_FIELD_SEEK_SIMPLE
        raw_obj = (1, 2, 'test1', 'test2')
        w = minipb.Wire('V2@2U@10U@20')
        self.assertEqual(w.encode(*raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), raw_obj)

    def test_field_seek_kvfmt_simple(self):
        '''
        Field seek with key-value format list: simple.
        '''
        expected_pb = TEST_FIELD_SEEK_SIMPLE
        raw_obj = {
            'arg1': 1,
            'arg2': 2,
            'arg3': 'test1',
            'arg4': 'test2',
        }
        schema = (
            ('arg1', 'V@2'),
            ('arg2', 'V'),
            ('arg3', 'U@10'),
            ('arg4', 'U@20'),
        )
        w = minipb.Wire(schema)
        self.assertEqual(w.encode(raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), raw_obj)

    def test_field_seek_fmtstr_complex(self):
        '''
        Field seek with format string: complex.
        '''
        expected_pb = TEST_FIELD_SEEK_COMPLEX
        raw_obj = (
            (1, 'hello'), (
                ('str1', ),
                ('str2', ),
            ),
        )
        w = minipb.Wire('[vU@10]@20+[U@2]@30')
        self.assertEqual(w.encode(*raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), raw_obj)

    def test_field_seek_kvfmt_complex(self):
        '''
        Field seek with key-value format list: complex.
        '''
        expected_pb = TEST_FIELD_SEEK_COMPLEX
        raw_obj = {
            'msg1': {
                'code': 1,
                'desc': 'hello',
            },
            'msg2': (
                {'str': 'str1'},
                {'str': 'str2'},
            ),
        }
        schema = (
            ('msg1', '[@20', (
                ('code', 'v'),
                ('desc', 'U@10'),
            )),
            ('msg2', '+[@30', (
                ('str', 'U@2'),
            )),
        )
        w = minipb.Wire(schema)
        self.assertEqual(w.encode(raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), raw_obj)

    def test_badbehavior_missing_field_kvfmt(self):
        '''
        Bad behavior: should raise exception on undefined fields when allow_sparse_dict=False.
        '''
        schema = (
            ('field1', 'V'),
            ('field2', 'V'),
        )
        w = minipb.Wire(schema)
        with self.assertRaises(minipb.CodecError) as details:
            w.encode({ 'field2': 123 })
        self.assertIn('empty field field1 not padded with None', details.exception.args[0])

    def test_badbehavior_missing_field_fmtstr(self):
        '''
        Bad behavior: should raise exception on missing tuple fields when using format string.
        '''
        w = minipb.Wire('V2')
        with self.assertRaises(minipb.CodecError) as details:
            w.encode(321)
        self.assertIn('empty field 2 not padded with None', details.exception.args[0])

    def test_badbehavior_chopped_message_str(self):
        '''
        Bad behavior: should raise exception when decoding truncated messages.
        '''
        expected_pb = b'\x12\x07\x74\x65\x73\x74\x69'
        with self.assertRaises(minipb.CodecError) as details:
            minipb.decode('xU', expected_pb)
        self.assertIn('Unexpected end of message', details.exception.args[0])

    def test_badbehavior_chopped_message_vint(self):
        '''
        Bad behavior: should raise exception when decoding truncated vint.
        '''
        expected_pb = b'\x08\x96'
        with self.assertRaises(minipb.CodecError) as details:
            minipb.decode('V', expected_pb)
        self.assertIn('Unexpected end of message', details.exception.args[0])

    def test_badbehavior_chopped_message_fixed32(self):
        '''
        Bad behavior: should raise exception when decoding truncated fixed32.
        '''
        expected_pb = b'\r\xff\x00'
        with self.assertRaises(minipb.CodecError) as details:
            minipb.decode('I', expected_pb)
        self.assertIn('Unexpected end of message', details.exception.args[0])

    def test_badbehavior_chopped_message_fixed64(self):
        '''
        Bad behavior: should raise exception when decoding truncated fixed64.
        '''
        expected_pb = b'\t\xff\x00'
        with self.assertRaises(minipb.CodecError) as details:
            minipb.decode('Q', expected_pb)
        self.assertIn('Unexpected end of message', details.exception.args[0])

    def test_badbehavior_fmtstr_field_seek_overlap_single(self):
        '''
        Bad behavior: should raise exception when one field overlap with another.
        '''
        with self.assertRaises(minipb.BadFormatString) as details:
            minipb.Wire('VU@1')
        self.assertIn('Multiple definitions found', details.exception.args[0])

    def test_badbehavior_fmtstr_field_seek_overlap_range_single(self):
        '''
        Bad behavior: should raise exception when one field range overlap with a field.
        '''
        with self.assertRaises(minipb.BadFormatString) as details:
            minipb.Wire('V3@1U@2')
        self.assertIn('Multiple definitions found', details.exception.args[0])

    def test_badbehavior_fmtstr_field_seek_overlap_range(self):
        '''
        Bad behavior: should raise exception when one field range overlap with another range.
        '''
        with self.assertRaises(minipb.BadFormatString) as details:
            minipb.Wire('V3@1U2@2')
        self.assertIn('Multiple definitions found', details.exception.args[0])
        self.assertIn('more fields after it', details.exception.args[0])

    def test_badbehavior_fmtstr_field_seek_overlap_single_range(self):
        '''
        Bad behavior: should raise exception when one field range overlap with another range.
        '''
        with self.assertRaises(minipb.BadFormatString) as details:
            minipb.Wire('V@3U3@1')
        self.assertIn('Multiple definitions found', details.exception.args[0])
        self.assertIn('more fields after it', details.exception.args[0])

    def test_badbehavior_kvfmt_field_seek_overlap_single(self):
        '''
        Bad behavior: should raise exception when one field overlap with another.
        '''
        with self.assertRaises(minipb.BadFormatString) as details:
            minipb.Wire((
                ('a', 'V'),
                ('b', 'U@1'),
            ))
        self.assertIn('Multiple definitions found', details.exception.args[0])

    def test_badbehavior_kvfmt_field_seek_overlap_range_single(self):
        '''
        Bad behavior: should raise exception when one field range overlap with a field.
        '''
        with self.assertRaises(minipb.BadFormatString) as details:
            minipb.Wire((
                ('_', 'x3@1'),
                ('a', 'U@2'),
            ))
        self.assertIn('Multiple definitions found', details.exception.args[0])

    def test_badbehavior_kvfmt_field_seek_overlap_range(self):
        '''
        Bad behavior: should raise exception when one field range overlap with another range.
        '''
        with self.assertRaises(minipb.BadFormatString) as details:
            minipb.Wire((
                ('_', 'x3@1'),
                ('_', 'x2@2'),
            ))
        self.assertIn('Multiple definitions found', details.exception.args[0])
        self.assertIn('more fields after it', details.exception.args[0])

    def test_badbehavior_kvfmt_field_seek_overlap_single_range(self):
        '''
        Bad behavior: should raise exception when one field range overlap with another range.
        '''
        with self.assertRaises(minipb.BadFormatString) as details:
            minipb.Wire((
                ('a', 'V@3'),
                ('_', 'x3@1'),
            ))
        self.assertIn('Multiple definitions found', details.exception.args[0])
        self.assertIn('more fields after it', details.exception.args[0])

if __name__ == '__main__':
    unittest.main()
