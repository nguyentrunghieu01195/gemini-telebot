import unittest

from api.utils import split_telegram_text


class SplitTelegramTextTests(unittest.TestCase):
    def test_short_text_is_unchanged(self):
        self.assertEqual(split_telegram_text("hello"), ["hello"])

    def test_long_text_respects_limit_and_round_trips_words(self):
        text = " ".join(["gemini"] * 2_000)
        chunks = split_telegram_text(text, limit=100)

        self.assertTrue(all(0 < len(chunk) <= 100 for chunk in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_invalid_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            split_telegram_text("hello", limit=4097)


if __name__ == "__main__":
    unittest.main()
