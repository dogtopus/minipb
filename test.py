#!/usr/bin/env python3
import unittest
import minipb


class TestMiniPB(unittest.TestCase):
    # some of the following data were taken from
    # https://developers.google.com/protocol-buffers/docs/encoding
    def test_codec_vint(self):
        expected_pb = b'\x08\x96\x01'
        raw_obj = 150
        self.assertEqual(minipb.encode('V', raw_obj), expected_pb)
        self.assertEqual(minipb.decode('V', expected_pb)[0], raw_obj)

    def test_codec_str(self):
        expected_pb = b'\x12\x07\x74\x65\x73\x74\x69\x6e\x67'
        raw_obj = 'testing'
        self.assertEqual(minipb.encode('xU', raw_obj), expected_pb)
        self.assertEqual(minipb.decode('xU', expected_pb)[0], raw_obj)

    def test_codec_packed_repeated_field(self):
        expected_pb = b'\x22\x06\x03\x8e\x02\x9e\xa7\x05'
        raw_obj = (3, 270, 86942)
        self.assertEqual(minipb.encode('x3#V', raw_obj), expected_pb)
        self.assertEqual(minipb.decode('x3#V', expected_pb)[0], raw_obj)

    def test_codec_packed_repeated_field_double_decode(self):
        expected_pb = b'\x22\x06\x03\x8e\x02\x9e\xa7\x05' * 2
        raw_obj = (3, 270, 86942) * 2
        self.assertEqual(minipb.decode('x3#V', expected_pb)[0], raw_obj)

    def test_codec_nested_message(self):
        expected_pb = b'\x1a\x03\x08\x96\x01'
        raw_obj = (150, )
        self.assertEqual(minipb.encode('x2[V]', raw_obj), expected_pb)
        self.assertEqual(minipb.decode('x2[V]', expected_pb)[0], raw_obj)

    def test_codec_fixed(self):
        expected_pb = b'\r\xff\xff\xff\xff\x15\x01\x00\x00\x00\x1d\x00\x00\x80?!\xcc\xe3# \xfd\xff\xff\xff)\xd2\x02\x96I\x00\x00\x00\x001\x18-DT\xfb!\t@'
        fields = (-1, 1, 1.0, -12345678900, 1234567890, 3.141592653589793)
        self.assertEqual(minipb.encode('iIfqQd', *fields), expected_pb)
        self.assertEqual(minipb.decode('iIfqQd', expected_pb), fields)

    def test_codec_vint_field(self):
        expected_pb = b'\x80\x01\x01'
        fields = (1,)
        # Field 16 requires 2 bytes
        self.assertEqual(minipb.encode('x15V', *fields), expected_pb)
        self.assertEqual(minipb.decode('x15V', expected_pb), fields)

    def test_codec_vint_2sc_negative(self):
        expected_pb = b'\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01'
        fields = (-1,)
        self.assertEqual(minipb.encode('t', *fields), expected_pb)
        self.assertEqual(minipb.decode('t', expected_pb), fields)

    def test_codec_vint_2sc_negative_force_32(self):
        expected_pb = b'\x08\xff\xff\xff\xff\x0f'
        fields = (-1,)
        w = minipb.Wire('t')
        w.vint_2sc_max_bits = 32
        self.assertEqual(w.encode(*fields), expected_pb)
        self.assertEqual(w.decode(expected_pb), fields)

    def test_kvfmt_single(self):
        expected_pb = b'\x08\x96\x01'
        raw_obj = {'value': 150}
        schema = (('value', 'V'),)
        w = minipb.Wire(schema)
        self.assertEqual(w.encode(raw_obj), expected_pb)
        self.assertEqual(w.decode(expected_pb), raw_obj)

    def test_kvfmt_complex(self):
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

    def test_badbehavior_missing_field_kvfmt(self):
        schema = (
            ('field1', 'V'),
            ('field2', 'V'),
        )
        w = minipb.Wire(schema)
        with self.assertRaises(minipb.CodecError) as details:
            w.encode({ 'field2': 123 })
        self.assertIn('empty field field1 not padded with None', details.exception.args[0])

    def test_badbehavior_missing_field_fmtstr(self):
        w = minipb.Wire('V2')
        with self.assertRaises(minipb.CodecError) as details:
            w.encode(321)
        self.assertIn('empty field 2 not padded with None', details.exception.args[0])

if __name__ == '__main__':
    unittest.main()
