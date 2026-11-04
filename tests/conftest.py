import os
import sys

os.environ.update(
    API_ID="12345", API_HASH="abc", BOT_TOKEN="123:abc", OWNER="111",
    ADMINS="222 333", MAP_SITES="weebc mgeko 18fx ma18 mhpu as", SETTLE_SECONDS="0", DB_URL="mongodb://127.0.0.1:27017", DB_NAME="testdb",
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from mongomock_motor import AsyncMongoMockClient

from Tools.db import database


@pytest.fixture(autouse=True)
def fake_db():
    """Point the global `database` singleton at a fresh in-memory MongoDB."""
    client = AsyncMongoMockClient()
    db = client["testdb"]
    database._db = db
    database.users = db.users
    database.acollection = db.premium
    database.tokens = db.user_tokens
    yield database


class FakeMsg:
    """Minimal stand-in for a pyrogram Message."""
    def __init__(self, id, empty=False, document=None, text=None, caption=None, photo=None, chat_id=-100):
        self.id, self.empty, self.document = id, empty, document
        self.text, self.caption, self.photo = text, caption, photo
        self.link = f"https://t.me/c/{abs(chat_id)}/{id}"
        self.chat = type("C", (), {"id": chat_id})()

    async def delete(self):
        self.empty = True


class FakeChannel:
    """In-memory channel: ids -> messages."""
    def __init__(self, chat_id, title):
        self.id, self.title, self.invite_link, self.pinned_message = chat_id, title, "https://t.me/+inv", None
        self.messages = {}
        self.next_id = 1

    def post(self, **kw):
        m = FakeMsg(self.next_id, chat_id=self.id, **kw)
        self.messages[m.id] = m
        self.next_id += 1
        return m


@pytest.fixture(autouse=True)
def _no_live_series_pages(monkeypatch):
    """Tests never touch real sites: on-demand series details return nothing unless a test sets them."""
    from Tools import details

    async def none(url):
        return {"poster": None, "description": "", "genres": [], "status": ""}
    monkeypatch.setattr(details, "fetch_details", none)
