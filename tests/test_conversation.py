import unittest

from api.conversation import ConversationMemory


class ConversationMemoryTests(unittest.TestCase):
    def test_stores_complete_exchange(self):
        memory = ConversationMemory()
        memory.add_exchange("chat", "Tên tôi là An", "Chào An")

        self.assertEqual([item["role"] for item in memory.get("chat")], ["user", "model"])
        self.assertEqual(memory.get("chat")[0]["parts"][0]["text"], "Tên tôi là An")

    def test_histories_are_isolated(self):
        memory = ConversationMemory()
        memory.add_exchange("chat-a", "A", "A1")

        self.assertEqual(memory.get("chat-b"), [])

    def test_trims_complete_exchanges(self):
        memory = ConversationMemory(max_messages=2, max_characters=100)
        memory.add_exchange("chat", "old", "old answer")
        memory.add_exchange("chat", "new", "new answer")

        history = memory.get("chat")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["parts"][0]["text"], "new")

    def test_clear(self):
        memory = ConversationMemory()
        memory.add_exchange("chat", "hello", "hi")

        self.assertTrue(memory.clear("chat"))
        self.assertEqual(memory.get("chat"), [])
        self.assertFalse(memory.clear("chat"))


if __name__ == "__main__":
    unittest.main()
