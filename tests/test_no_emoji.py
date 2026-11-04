"""The UI must never contain an emoji: not in the source, not after styling."""
import glob
import re

from Tools.style import style_text

EMOJI = re.compile("[\U0001F000-\U0001FAFF️‍"
                   "✅❌❗⚠⛔⚡⚪⚫⏳⌛⏸⏭⏩⏪▶◀"
                   "✔✖❤♥☑✂⬆⬇➡⬅✨⭐☠⚙‼]")


def test_source_files_contain_no_emoji():
    bad = []
    for path in glob.glob("TG/*.py") + glob.glob("Tools/*.py") + ["bot.py", "main.py", "config.py"]:
        if path.endswith("style.py"):
            continue
        for n, line in enumerate(open(path, encoding="utf8"), 1):
            if EMOJI.search(line):
                bad.append(f"{path}:{n}")
    assert not bad, bad[:10]


def test_styling_removes_every_emoji_even_unknown_ones():
    messy = "done ✅ ❌ ⚠️ 🎉 🧑‍💻 ▶ ◀ ✔ ✖ ☠ ⏸ ⚡ ❤ 🇮🇳"
    assert not EMOJI.search(style_text(messy))
