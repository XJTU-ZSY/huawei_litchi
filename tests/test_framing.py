from __future__ import annotations

import unittest

from litchi_bot.protocol.framing import FrameDecodeError, FrameDecoder, encode_frame


class FramingTests(unittest.TestCase):
    def test_encode_frame_uses_utf8_body_length(self) -> None:
        message = {"msg_name": "test", "msg_data": {"text": "荔枝"}}

        frame = encode_frame(message)

        self.assertEqual(int(frame[:5]), len(frame) - 5)
        self.assertEqual(FrameDecoder().feed(frame), [message])

    def test_decoder_handles_split_frame(self) -> None:
        message = {"msg_name": "inquire", "msg_data": {"round": 7}}
        frame = encode_frame(message)
        decoder = FrameDecoder()

        self.assertEqual(decoder.feed(frame[:2]), [])
        self.assertEqual(decoder.feed(frame[2:9]), [])
        self.assertEqual(decoder.feed(frame[9:]), [message])
        self.assertEqual(decoder.pending_bytes, 0)

    def test_decoder_handles_sticky_frames(self) -> None:
        first = {"msg_name": "inquire", "msg_data": {"round": 1}}
        second = {"msg_name": "over", "msg_data": {"winner": "RED"}}
        decoder = FrameDecoder()

        self.assertEqual(decoder.feed(encode_frame(first) + encode_frame(second)), [first, second])

    def test_decoder_rejects_invalid_prefix(self) -> None:
        with self.assertRaises(FrameDecodeError):
            FrameDecoder().feed(b"abcde{}")


if __name__ == "__main__":
    unittest.main()
