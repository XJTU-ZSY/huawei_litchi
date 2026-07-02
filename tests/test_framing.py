import unittest

from litchi_bot.framing import FrameDecoder, ProtocolError, encode_frame


class FramingTest(unittest.TestCase):
    def test_round_trip(self):
        message = {"msg_name": "inquire", "msg_data": {"text": "荔枝", "round": 1}}
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(encode_frame(message)), [message])

    def test_half_packet(self):
        message = {"msg_name": "action", "msg_data": {"actions": []}}
        frame = encode_frame(message)
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(frame[:3]), [])
        self.assertEqual(decoder.feed(frame[3:]), [message])

    def test_sticky_packets(self):
        first = {"msg_name": "start", "msg_data": {"matchId": "m"}}
        second = {"msg_name": "over", "msg_data": {"matchId": "m"}}
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(encode_frame(first) + encode_frame(second)), [first, second])

    def test_invalid_prefix(self):
        with self.assertRaises(ProtocolError):
            FrameDecoder().feed(b"abcde{}")


if __name__ == "__main__":
    unittest.main()
