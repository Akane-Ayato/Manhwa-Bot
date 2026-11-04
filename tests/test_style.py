from Tools.style import style_text, install


def test_small_caps_and_symbols():
    assert style_text("Queue is empty") == "Qᴜᴇᴜᴇ ɪꜱ ᴇᴍᴘᴛʏ"
    assert style_text("✅ Done ❌ failed") == "✓ Dᴏɴᴇ ✗ ꜰᴀɪʟᴇᴅ"
    assert style_text("🟢 on · 🔴 off ⚠️ careful") == "● ᴏɴ · ◉ ᴏꜰꜰ ▲ ᴄᴀʀᴇꜰᴜʟ"
    assert "🎉" not in style_text("party 🎉")          # unknown emoji removed


def test_protected_parts_are_untouched():
    src = ("Use /add or /manage, ask @some_user at https://t.me/abc/def now "
           "<code>file name.pdf</code> <b>bold text</b> `inline code` &lt;id&gt; {placeholder}")
    out = style_text(src)
    for keep in ("/add", "/manage", "@some_user", "https://t.me/abc/def", "<code>file name.pdf</code>",
                 "`inline code`", "&lt;", "{placeholder}", "<b>", "</b>"):
        assert keep in out
    assert out.startswith("Uꜱᴇ ") and "<b>ʙᴏʟᴅ ᴛᴇxᴛ</b>" in out and "&lt;ɪᴅ&gt;" in out


def test_idempotent_and_non_text_passthrough():
    once = style_text("Hello world ✅")
    assert style_text(once) == once
    assert style_text(None) is None and style_text("") == ""


def test_install_patches_buttons_and_message_methods():
    from pyrogram.types import InlineKeyboardButton, Message
    n = install()
    assert install() == 0                                   # second call patches nothing
    b = InlineKeyboardButton("Next page", callback_data="x")
    assert b.text == "Nᴇxᴛ ᴘᴀɢᴇ"
    assert getattr(Message.reply_text, "_styled", False)
