import unittest

from app.bot import handle_telegram_webhook


class BotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sent = []

    async def send(self, chat_id, text):
        self.sent.append((chat_id, text))

    async def projects(self):
        return [{"name": "Example"}]

    async def call(self, update, secret="secret", configured_secret="secret", owner_id=42):
        return await handle_telegram_webhook(update, secret, configured_secret, owner_id, self.projects, self.send)

    def message(self, text, user=42, chat=42, kind="private"):
        return {"message": {"from": {"id": user}, "chat": {"id": chat, "type": kind}, "text": text}}

    async def test_owner_can_list_projects(self):
        self.assertEqual(await self.call(self.message("/projects")), 200)
        self.assertEqual(self.sent, [(42, "Loyihalar:\n• Example")])

    async def test_rejects_bad_or_missing_secret(self):
        self.assertEqual(await self.call(self.message("/start"), secret="bad"), 403)
        self.assertEqual(await self.call(self.message("/start"), configured_secret=None), 503)
        self.assertEqual(self.sent, [])

    async def test_ignores_non_owner_and_group_messages(self):
        for update in (self.message("/start", user=41), self.message("/start", chat=99), self.message("/start", kind="group")):
            self.assertEqual(await self.call(update), 200)
        self.assertEqual(self.sent, [])

    async def test_requires_owner_configuration(self):
        self.assertEqual(await self.call(self.message("/start"), owner_id=None), 503)
        self.assertEqual(self.sent, [])

    async def test_help_and_unknown_command(self):
        self.assertEqual(await self.call(self.message("/help")), 200)
        self.assertIn("/projects", self.sent[-1][1])
        self.assertEqual(await self.call(self.message("/other")), 200)
        self.assertIn("/help", self.sent[-1][1])


if __name__ == "__main__":
    unittest.main()
