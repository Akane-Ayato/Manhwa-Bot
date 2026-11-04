"""Progress bars for the download -> build -> upload pipeline.

Every TaskCard owns a `Progress`.  The pipeline only calls cheap, synchronous
methods (`set_stage`, `update`); the status message is edited by `push()`, which
is throttled (Telegram rate-limits message edits) and never raises.
"""
import asyncio
import time
from typing import Optional

BAR_FULL, BAR_EMPTY = "▰", "▱"
MIN_EDIT_GAP = 3.0  # seconds between two edits of the same status message

STAGES = ("Waiting", "Fetching", "Downloading", "Building", "Uploading", "Posted", "Failed")


def bar(percent: float, width: int = 10) -> str:
    percent = max(0.0, min(100.0, float(percent or 0)))
    filled = int(round(width * percent / 100))
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def fmt_size(num: float) -> str:
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def fmt_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "--"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


class Progress:
    """State of one task: current stage plus done/total of the running stage."""

    def __init__(self):
        self.stage = "Waiting"
        self.done = 0.0
        self.total = 0.0
        self.unit = ""            # "pages" or "bytes"
        self.stage_started = time.monotonic()
        self.started = time.monotonic()
        self.detail = ""
        self._last_edit = 0.0
        self._last_text = None
        self._editing = False

    # ---- state ----------------------------------------------------------
    def set_stage(self, stage: str, total: float = 0, unit: str = "", detail: str = "") -> None:
        self.stage = stage
        self.done = 0.0
        self.total = float(total or 0)
        self.unit = unit
        self.detail = detail
        self.stage_started = time.monotonic()

    def update(self, done: float, total: Optional[float] = None) -> None:
        self.done = float(done or 0)
        if total:
            self.total = float(total)

    # ---- numbers --------------------------------------------------------
    @property
    def percent(self) -> float:
        if self.stage in ("Posted",):
            return 100.0
        if not self.total:
            return 0.0
        return min(100.0, self.done * 100.0 / self.total)

    @property
    def speed(self) -> float:
        """units per second inside the current stage."""
        elapsed = time.monotonic() - self.stage_started
        return self.done / elapsed if elapsed > 0.2 else 0.0

    @property
    def eta(self) -> Optional[float]:
        speed = self.speed
        if not speed or not self.total:
            return None
        return (self.total - self.done) / speed

    # ---- text -----------------------------------------------------------
    def line(self, width: int = 10) -> str:
        """`Downloading ▰▰▰▱▱▱▱▱▱▱ 30%  (15/50 pages)  ETA 12s`"""
        text = f"{self.stage} {bar(self.percent, width)} {self.percent:.0f}%"
        if self.total and self.unit == "pages":
            text += f"  ({int(self.done)}/{int(self.total)} pages)"
        elif self.total and self.unit == "bytes":
            text += f"  ({fmt_size(self.done)}/{fmt_size(self.total)})"
        if self.stage in ("Downloading", "Uploading") and self.total:
            if self.unit == "bytes" and self.speed:
                text += f"\nϟ {fmt_size(self.speed)}/s"
            eta = self.eta
            if eta is not None:
                text += f"  ⧖ {fmt_eta(eta)}"
        if self.detail:
            text += f"\n{self.detail}"
        return text


def render_card(card, position: Optional[int] = None, waiting: int = 0) -> str:
    """Full status-message text for a TaskCard."""
    prog = getattr(card, "progress", None) or Progress()
    title = f"{getattr(card, 'orginal_manga_title', '') or getattr(card, 'manga_title', '')}"
    ep = getattr(card, "episode_number", "")
    head = f"❖ <b>{title}</b> — Ch {ep}".rstrip()
    target = getattr(card, "target_title", None)
    if target:
        head += f"\n➥ {target}"
    body = f"<code>{prog.line()}</code>"
    tail = ""
    if waiting:
        tail = f"\n≡ Queue: {waiting} waiting"
    return f"{head}\n\n{body}{tail}"


async def push(card, force: bool = False) -> None:
    """Edit the task's status message (throttled; never raises).  No status message -> no-op."""
    sts = getattr(card, "sts", None)
    prog = getattr(card, "progress", None)
    if sts is None or prog is None or prog._editing:
        return
    now = time.monotonic()
    if not force and now - prog._last_edit < MIN_EDIT_GAP:
        return

    text = render_card(card)
    if text == prog._last_text:
        return

    prog._editing = True
    try:
        await sts.edit(text)
        prog._last_text = text
    except asyncio.CancelledError:
        raise
    except Exception as err:  # MessageNotModified, FloodWait, deleted message ... never fatal
        wait = getattr(err, "value", None)
        if isinstance(wait, (int, float)):
            prog._last_edit = now + wait  # back off for as long as Telegram asked
    finally:
        prog._last_edit = max(prog._last_edit, time.monotonic())
        prog._editing = False


def schedule_push(card) -> None:
    """Fire-and-forget push, usable from sync progress callbacks (inside the event loop)."""
    prog = getattr(card, "progress", None)
    if getattr(card, "sts", None) is None or prog is None:
        return
    if time.monotonic() - prog._last_edit < MIN_EDIT_GAP or prog._editing:
        return
    try:
        asyncio.get_running_loop().create_task(push(card))
    except RuntimeError:
        pass  # no running loop (e.g. called from a worker thread) - skip this tick
