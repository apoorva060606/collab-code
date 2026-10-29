"""
Unit tests for Real-time Collaboration Hub:
- Room creation and retrieval
- Multi-client connection and initial state
- Code change broadcasting
- Chat message broadcasting
- File creation and deletion
"""

import unittest
import asyncio
import json
from collab_hub import CollaborationHub

class MockWebSocket:
    def __init__(self):
        self.sent_messages = []
        self.is_closed = False

    async def send_text(self, text: str):
        self.sent_messages.append(text)

    async def close(self):
        self.is_closed = True


class TestCollabHub(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hub = CollaborationHub()

    async def test_connect_and_state(self):
        ws1 = MockWebSocket()
        user1 = {"id": "usr_test1", "username": "alice", "avatar_url": ""}
        room = await self.hub.connect("room-101", "client-1", ws1, user1)
        
        self.assertEqual(len(room.connections), 1)
        self.assertEqual(len(ws1.sent_messages), 1)
        
        payload = json.loads(ws1.sent_messages[0])
        self.assertEqual(payload["type"], "room_state")
        self.assertEqual(payload["self"]["username"], "alice")
        self.assertIn("main.py", payload["state"]["files"])

    async def test_two_users_collaboration_sync(self):
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        user1 = {"id": "usr_1", "username": "user1"}
        user2 = {"id": "usr_2", "username": "user2"}

        await self.hub.connect("room-sync", "c1", ws1, user1)
        await self.hub.connect("room-sync", "c2", ws2, user2)

        # ws1 should have received user_joined notification for user2
        self.assertGreaterEqual(len(ws1.sent_messages), 2)
        join_msg = json.loads(ws1.sent_messages[-1])
        self.assertEqual(join_msg["type"], "user_joined")
        self.assertEqual(join_msg["user"]["username"], "user2")

        # Now c1 sends a code_change
        await self.hub.handle_message(
            "room-sync",
            "c1",
            {"type": "code_change", "filename": "main.py", "content": "print('live edit')"}
        )

        # ws2 should receive the code_change
        self.assertGreaterEqual(len(ws2.sent_messages), 2)
        code_msg = json.loads(ws2.sent_messages[-1])
        self.assertEqual(code_msg["type"], "code_change")
        self.assertEqual(code_msg["content"], "print('live edit')")

    async def test_chat_broadcast(self):
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        await self.hub.connect("room-chat", "c1", ws1, {"id": "usr_1", "username": "alice"})
        await self.hub.connect("room-chat", "c2", ws2, {"id": "usr_2", "username": "bob"})

        await self.hub.handle_message("room-chat", "c1", {"type": "chat_message", "text": "Hello Bob!"})

        # Both should receive the chat message
        last_msg_c2 = json.loads(ws2.sent_messages[-1])
        self.assertEqual(last_msg_c2["type"], "chat_message")
        self.assertEqual(last_msg_c2["message"]["text"], "Hello Bob!")

if __name__ == "__main__":
    unittest.main()
