import ctypes
import json
import os
import random
import sys
import tkinter as tk
import time
import queue
import threading
from dataclasses import dataclass

from PIL import Image, ImageTk

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows fallback
    winsound = None


WINDOW_BG = "#fff7ef"
PANEL_BG = "#fffdf9"
PANEL_LIGHT = "#fff0e5"
BOARD_BG = "#fffaf5"
GRID_LINE = "#ead9cc"
GRID_DOT = "#d7b9a8"
TEXT = "#5b4651"
TEXT_MUTED = "#947a7d"
ACCENT = "#d98274"
ACCENT_DARK = "#d98274"
DANGER = "#dc7075"
GOLD = "#e7ad70"
BUTTON_HOVER = "#c96f63"
SECONDARY = "#e7b7aa"
INK = "#6b5560"
BORDER = "#e5c9ba"
HELPER = "#b58f8c"
CELL = 58
PADDING = 20
WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 900

ASSET_DIR = os.path.join(
    getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets"
)
WIN_IMAGE_NAME = "result_win"
FAIL_IMAGE_NAME = "result_fail"
RESULT_IMAGE_BOX = (300, 240)
RESULT_FRAME_DELAY_MS = 100
SAVE_FILE_NAME = "savegame.json"
SOUND_NAMES = {
    "fly": "arrow_fly.wav",
    "collision": "arrow_collision.wav",
    "win": "level_win.wav",
    "fail": "level_fail.wav",
}
SOUND_QUEUE = queue.Queue()

DIRECTIONS = {
    "U": (-1, 0, "上"),
    "D": (1, 0, "下"),
    "L": (0, -1, "左"),
    "R": (0, 1, "右"),
}
ARROW_COLORS = {"U": "#a9d8bd", "D": "#a9d6e6", "L": "#f4b6c5", "R": "#f6d58e"}


@dataclass
class Arrow:
    row: int
    col: int
    direction: str
    active: bool = True


def make_arrows(values):
    return [Arrow(row, col, direction) for row, col, direction in values]


def line_direction_stats(arrows):
    """Measure repeated directions along each occupied row and column."""
    lines = {}
    for arrow in arrows:
        lines.setdefault(("row", arrow.row), []).append((arrow.col, arrow.direction))
        lines.setdefault(("col", arrow.col), []).append((arrow.row, arrow.direction))

    max_run = 1
    repeated_pairs = 0
    for line in lines.values():
        line.sort()
        run = 1
        for previous, current in zip(line, line[1:]):
            if current[0] == previous[0] + 1 and previous[1] == current[1]:
                run += 1
                repeated_pairs += 1
                max_run = max(max_run, run)
            else:
                run = 1
    return max_run, repeated_pairs


def _arrow_reaches_cell(arrow, row, col, rows, cols):
    """Return whether an arrow's path crosses a target cell."""
    dr, dc, _ = DIRECTIONS[arrow.direction]
    current_row, current_col = arrow.row + dr, arrow.col + dc
    while 0 <= current_row < rows and 0 <= current_col < cols:
        if current_row == row and current_col == col:
            return True
        current_row += dr
        current_col += dc
    return False


def _random_solvable_layout(rows, cols, count, seed):
    """Create a shuffled board while constructing a guaranteed clear order.

    The generator chooses an arrow that is clear among the cells still being
    built, then removes that cell from the temporary set. It may point through
    already removed cells, which creates real dependencies without creating a
    cycle. The final list is shuffled so the board is visually unordered.
    """
    rng = random.Random(seed)
    all_positions = [(row, col) for row in range(rows) for col in range(cols)]
    for _ in range(500):
        positions = rng.sample(all_positions, count)
        row_counts = {row: sum(position[0] == row for position in positions) for row in range(rows)}
        col_counts = {col: sum(position[1] == col for position in positions) for col in range(cols)}
        if max(row_counts.values()) < cols and max(col_counts.values()) < rows:
            break
    else:
        raise RuntimeError("无法生成分布均匀的随机关卡")
    remaining = set(positions)
    removed = []
    direction_counts = {direction: 0 for direction in DIRECTIONS}

    while remaining:
        candidates = []
        for row, col in remaining:
            for direction in rng.sample(list(DIRECTIONS), len(DIRECTIONS)):
                candidate = Arrow(row, col, direction)
                blocked_by_remaining = any(
                    _arrow_reaches_cell(candidate, target_row, target_col, rows, cols)
                    for target_row, target_col in remaining
                    if (target_row, target_col) != (row, col)
                )
                if blocked_by_remaining:
                    continue
                same_direction_neighbor = any(
                    arrow.direction == direction
                    and (
                        (arrow.row == row and abs(arrow.col - col) == 1)
                        or (arrow.col == col and abs(arrow.row - row) == 1)
                    )
                    for arrow in removed
                )
                if same_direction_neighbor:
                    continue
                links = sum(
                    _arrow_reaches_cell(candidate, arrow.row, arrow.col, rows, cols)
                    for arrow in removed
                )
                candidates.append((links, rng.random(), candidate))

        if not candidates:
            raise RuntimeError("无法生成可通关的随机关卡")

        highest_links = max(item[0] for item in candidates)
        threshold = max(0, highest_links - (1 if rng.random() < 0.8 else 0))
        pool = [item for item in candidates if item[0] >= threshold]
        least_used = min(direction_counts[item[2].direction] for item in pool)
        balanced_pool = [
            item for item in pool
            if direction_counts[item[2].direction] == least_used
        ]
        _links, _random_value, choice = rng.choice(balanced_pool)
        removed.append(choice)
        direction_counts[choice.direction] += 1
        remaining.remove((choice.row, choice.col))

    rng.shuffle(removed)
    return removed


def build_random_level(rows, cols, count, seed, minimum_blocked):
    """Choose a solvable layout with obstacles and short direction runs."""
    best = None
    for attempt in range(160):
        try:
            arrows = _random_solvable_layout(rows, cols, count, seed + attempt * 7919)
        except RuntimeError:
            continue
        blocked = sum(
            any(
                other_index != index
                and _arrow_reaches_cell(arrow, other.row, other.col, rows, cols)
                for other_index, other in enumerate(arrows)
            )
            for index, arrow in enumerate(arrows)
        )
        if blocked >= minimum_blocked:
            max_run, repeated_pairs = line_direction_stats(arrows)
            rank = (max(0, max_run - 2), repeated_pairs, -blocked)
            if best is None or rank < best[0]:
                best = (rank, arrows)
            if max_run <= 2:
                return arrows
    if best is not None:
        return best[1]
    raise RuntimeError("随机关卡未达到目标难度")


LEVELS = [
    {"name": "启程", "subtitle": "熟悉四种方向与阻挡规则", "rows": 5, "cols": 5, "mistakes": 2, "difficulty": 1, "par_time": 35,
     "arrows": make_arrows([
         (0, 1, "U"), (1, 3, "R"), (2, 0, "R"), (2, 4, "D"),
         (4, 2, "D"), (3, 1, "L"), (1, 1, "D"), (4, 4, "L"),
     ])},
    {"name": "交错", "subtitle": "18 支箭头随机散落，寻找第一处突破口", "rows": 6, "cols": 6, "mistakes": 2, "difficulty": 2, "par_time": 55,
     "arrows": build_random_level(6, 6, 18, 1202, 7)},
    {"name": "回廊", "subtitle": "28 支箭头交叉分布，错误顺序会被连续阻挡", "rows": 7, "cols": 7, "mistakes": 2, "difficulty": 3, "par_time": 85,
     "arrows": build_random_level(7, 7, 28, 2303, 13)},
    {"name": "迷宫", "subtitle": "48 支箭头打乱方向，逐层拆解阻挡关系", "rows": 8, "cols": 8, "mistakes": 2, "difficulty": 4, "par_time": 120,
     "arrows": build_random_level(8, 8, 48, 3404, 24)},
    {"name": "终局", "subtitle": "61 支箭头高密度乱序，完成最后的路线推演", "rows": 9, "cols": 9, "mistakes": 2, "difficulty": 5, "par_time": 170,
     "arrows": build_random_level(9, 9, 61, 4505, 32)},
]


def calculate_level_score(level_index, elapsed_seconds, blocked_attempts):
    level = LEVELS[level_index]
    density_bonus = min(180, len(level["arrows"]) * 3)
    difficulty_bonus = level["difficulty"] * 45
    speed_bonus = min(300, max(0, level["par_time"] - elapsed_seconds) * 2)
    overtime_penalty = max(0, elapsed_seconds - level["par_time"]) * 3
    mistake_penalty = blocked_attempts * (35 + level["difficulty"] * 8)
    score = 420 + density_bonus + difficulty_bonus + speed_bonus - overtime_penalty - mistake_penalty
    return max(0, min(1000, round(score)))


def score_grade(score):
    if score >= 850:
        return "S"
    if score >= 700:
        return "A"
    if score >= 550:
        return "B"
    if score >= 400:
        return "C"
    return "D"


def find_blocker_in_state(arrows: list[Arrow], rows: int, cols: int, index: int):
    current = arrows[index]
    dr, dc, _ = DIRECTIONS[current.direction]
    row, col = current.row + dr, current.col + dc
    while 0 <= row < rows and 0 <= col < cols:
        for other_index, other in enumerate(arrows):
            if other_index != index and other.active and other.row == row and other.col == col:
                return other_index
        row, col = row + dr, col + dc
    return None


def find_clear_order(arrows: list[Arrow], rows: int, cols: int):
    """Return a safe step-by-step order for the currently active arrows."""
    original_active = [arrow.active for arrow in arrows]
    active = {index for index, arrow in enumerate(arrows) if arrow.active}
    order = []
    try:
        while active:
            next_index = next(
                (
                    index
                    for index in active
                    if find_blocker_in_state(arrows, rows, cols, index) is None
                ),
                None,
            )
            if next_index is None:
                return None
            order.append(next_index)
            arrows[next_index].active = False
            active.remove(next_index)
        return order
    finally:
        for arrow, was_active in zip(arrows, original_active):
            arrow.active = was_active


def enable_high_dpi():
    """Ask Windows to render the Tk window at native monitor DPI."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _sound_worker():
    """Play queued effects serially so sounds cannot interrupt one another."""
    while True:
        name = SOUND_QUEUE.get()
        try:
            if winsound is None:
                continue
            filename = SOUND_NAMES.get(name)
            if not filename:
                continue
            path = os.path.join(ASSET_DIR, filename)
            if os.path.exists(path):
                winsound.PlaySound(path, winsound.SND_FILENAME)
        except (OSError, RuntimeError):
            pass
        finally:
            SOUND_QUEUE.task_done()


if winsound is not None:
    threading.Thread(target=_sound_worker, name="arrow-sound-worker", daemon=True).start()


def play_sound(name):
    """Queue a local effect without blocking Tkinter animations."""
    if winsound is not None and name in SOUND_NAMES:
        SOUND_QUEUE.put(name)


class RoundedButton(tk.Canvas):
    """A compact rounded button that keeps the warm visual style consistent."""

    def __init__(self, parent, text, command, fill, foreground, hover_fill, font, width, height=48):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.button_text = text
        self.command = command
        self.fill_color = fill
        self.foreground = foreground
        self.hover_fill = hover_fill
        self.button_font = font
        self.button_width = width
        self.button_height = height
        self.button_state = "normal"
        self.disabled_foreground = TEXT_MUTED
        self.hovered = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _on_enter(self, _event):
        self.hovered = True
        self._draw()

    def _on_leave(self, _event):
        self.hovered = False
        self._draw()

    def _on_click(self, _event):
        if self.button_state != "disabled" and self.command is not None:
            self.command()

    def _draw(self):
        self.delete("all")
        disabled = self.button_state == "disabled"
        fill = "#f1e4dc" if disabled else (self.hover_fill if self.hovered else self.fill_color)
        foreground = self.disabled_foreground if disabled else self.foreground
        x1, y1 = 2, 2
        x2, y2 = self.button_width - 2, self.button_height - 2
        radius = min(16, (y2 - y1) // 2)
        self._rounded_rectangle(x1, y1, x2, y2, radius, fill)
        self.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            text=self.button_text,
            fill=foreground,
            font=self.button_font,
        )

    def _rounded_rectangle(self, x1, y1, x2, y2, radius, fill):
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
        self.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)
        for box, start in (
            ((x1, y1, x1 + radius * 2, y1 + radius * 2), 90),
            ((x2 - radius * 2, y1, x2, y1 + radius * 2), 0),
            ((x2 - radius * 2, y2 - radius * 2, x2, y2), 270),
            ((x1, y2 - radius * 2, x1 + radius * 2, y2), 180),
        ):
            self.create_arc(box, start=start, extent=90, fill=fill, outline=fill)

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf or {}) if isinstance(cnf, dict) else {}
        options.update(kwargs)
        if "state" in options:
            self.button_state = options.pop("state")
            self._draw()
        if "disabledforeground" in options:
            self.disabled_foreground = options.pop("disabledforeground")
            self._draw()
        if "text" in options:
            self.button_text = options.pop("text")
            self._draw()
        return super().configure(**options)

    config = configure

    def invoke(self):
        if self.button_state != "disabled" and self.command is not None:
            self.command()


class ArrowEscapeGame:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("箭路突围 | 方向解谜游戏")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(True, True)
        self.root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.maxsize(5000, 5000)
        self.root.configure(bg=WINDOW_BG)
        self.root.bind("<Key-r>", lambda _event: self.restart_level())
        self.root.bind("<Key-R>", lambda _event: self.restart_level())
        self.root.bind("<Key-h>", lambda _event: self.show_hint())
        self.root.bind("<Key-H>", lambda _event: self.show_hint())
        self.root.bind("<F11>", lambda _event: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda _event: self.handle_escape())
        self.root.bind("<Configure>", self.handle_configure)
        self.root.protocol("WM_DELETE_WINDOW", self.close_game)

        self.level_index = 0
        self.arrows = []
        self.mistakes_left = 0
        self.moves = 0
        self.blocked_attempts = 0
        self.elapsed_seconds = 0
        self.timer_started_at = None
        self.timer_id = None
        self.animating = False
        self.session_id = 0
        self.hover_index = None
        self.arrow_items = {}
        self.fullscreen = False
        self.current_view = "start"
        self.result_passed = False
        self.level_scores = {}
        self.max_unlocked_level = 0
        self.resize_after_id = None
        self.last_size = None
        self.result_frames = []
        self.result_frame_index = 0
        self.result_frame_job = None
        self.result_image_label = None
        self.result_frame_delays = []
        self.ui_scale = 1.0
        self.cell_size = CELL
        self.message = tk.StringVar()
        self.timer_text = tk.StringVar(value="00:00")
        self.ai_status = tk.StringVar(value="等待开始")
        self.ai_solving = False
        self.ai_after_id = None
        self.ai_button = None
        self.ai_step = 0
        self.container = tk.Frame(root, bg=WINDOW_BG)
        self.container.pack(fill="both", expand=True)
        self.show_start_screen()

    @property
    def save_path(self):
        base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_dir, SAVE_FILE_NAME)

    def close_game(self):
        if self.current_view == "game":
            self.save_progress()
        self.root.destroy()

    def save_progress(self, next_level=None):
        if self.current_view != "game" or not self.arrows:
            return False
        data = {
            "level_index": self.level_index,
            "next_level": next_level,
            "active": [arrow.active for arrow in self.arrows],
            "mistakes_left": self.mistakes_left,
            "moves": self.moves,
            "blocked_attempts": self.blocked_attempts,
            "elapsed_seconds": self.current_elapsed_seconds(),
            "level_scores": {str(key): value for key, value in self.level_scores.items()},
            "max_unlocked_level": self.max_unlocked_level,
        }
        try:
            with open(self.save_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False

    def read_saved_progress(self):
        try:
            with open(self.save_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            level_index = data.get("next_level")
            if level_index is None:
                level_index = data.get("level_index")
            if not isinstance(level_index, int) or not 0 <= level_index < len(LEVELS):
                return None
            active = data.get("active", [])
            if level_index == data.get("level_index") and len(active) != len(LEVELS[level_index]["arrows"]):
                return None
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def current_elapsed_seconds(self):
        if self.timer_started_at is None:
            return int(self.elapsed_seconds)
        return max(0, int(time.monotonic() - self.timer_started_at))

    def clear_saved_progress(self):
        try:
            os.remove(self.save_path)
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True

    def clear(self):
        if self.timer_id is not None:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        if self.ai_after_id is not None:
            self.root.after_cancel(self.ai_after_id)
            self.ai_after_id = None
        self.ai_solving = False
        self.ai_button = None
        self.stop_result_frame_playback()
        for widget in self.container.winfo_children():
            widget.destroy()

    def handle_escape(self):
        if self.fullscreen:
            self.toggle_fullscreen(False)
        else:
            self.return_to_menu()

    def toggle_fullscreen(self, enabled=None):
        if enabled is None:
            enabled = not self.fullscreen
        self.fullscreen = bool(enabled)
        if self.fullscreen:
            self.root.maxsize(5000, 5000)
            self.root.attributes("-fullscreen", True)
        else:
            self.root.attributes("-fullscreen", False)
            self.root.resizable(True, True)
            self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.schedule_resize()

    def handle_configure(self, event):
        """Ignore Configure events bubbled up from child widgets.

        Tk propagates a child widget's <Configure> to the toplevel binding tag,
        so rebuilding the UI used to retrigger this handler endlessly and made
        the screen flicker. Only a real toplevel size change may schedule work.
        """
        if event.widget is not self.root:
            return
        size = (self.root.winfo_width(), self.root.winfo_height())
        if size == self.last_size:
            return
        self.last_size = size
        self.schedule_resize()

    def schedule_resize(self):
        if self.resize_after_id is not None:
            self.root.after_cancel(self.resize_after_id)
        self.resize_after_id = self.root.after(100, self.refresh_layout)

    def refresh_layout(self):
        self.resize_after_id = None
        if self.animating:
            self.schedule_resize()
            return
        if self.current_view == "start":
            self.show_start_screen()
        elif self.current_view == "level_select":
            self.show_level_select()
        elif self.current_view == "game":
            self.load_level(self.level_index, preserve_state=True)
        elif self.current_view == "level_clear":
            self.show_level_clear()
        elif self.current_view == "result":
            self.show_result(self.result_passed)

    def prepare_surface(self):
        self.root.update_idletasks()
        width = max(WINDOW_WIDTH, self.root.winfo_width())
        height = max(WINDOW_HEIGHT, self.root.winfo_height())
        try:
            maximized = self.root.state() == "zoomed"
        except tk.TclError:
            maximized = False
        expanded = self.fullscreen or maximized
        self.ui_scale = min(width / WINDOW_WIDTH, height / WINDOW_HEIGHT) if expanded else 1.0
        surface_width = round(WINDOW_WIDTH * self.ui_scale)
        surface_height = round(WINDOW_HEIGHT * self.ui_scale)
        self.container.pack_forget()
        self.container.place(relx=0.5, rely=0.5, anchor="center", width=surface_width, height=surface_height)

    def px(self, value):
        return max(1, round(value * self.ui_scale))

    def ui_font(self, size, bold=False):
        return ("Microsoft YaHei UI", max(8, round(size * self.ui_scale)), "bold" if bold else "normal")

    def make_button(self, parent, text, command, color=ACCENT_DARK, width=12):
        foreground = "#fffaf5" if color in (ACCENT_DARK, ACCENT, BUTTON_HOVER) else INK
        button_width = self.px(max(132, round(width * 11 + 42)))
        button_height = self.px(52)
        return RoundedButton(
            parent,
            text,
            command,
            fill=color,
            foreground=foreground,
            hover_fill=BUTTON_HOVER if color in (ACCENT_DARK, ACCENT, BUTTON_HOVER) else "#d9a397",
            font=self.ui_font(11, bold=True),
            width=button_width,
            height=button_height,
        )

    def draw_background(self, canvas):
        width = self.px(WINDOW_WIDTH)
        height = self.px(WINDOW_HEIGHT)
        canvas.configure(width=width, height=height, bg=WINDOW_BG)
        for x in range(0, width, self.px(44)):
            canvas.create_line(x, 0, x, height, fill="#f8eadf")
        for y in range(0, height, self.px(44)):
            canvas.create_line(0, y, width, y, fill="#f8eadf")
        for x, y, color in [(72, 72, "#f4b6c5"), (925, 92, "#a9d8bd"), (90, 820, "#f6d58e"), (910, 820, "#a9d6e6")]:
            canvas.create_oval(self.px(x - 4), self.px(y - 4), self.px(x + 4), self.px(y + 4), fill=color, outline="")

    def show_start_screen(self):
        self.current_view = "start"
        self.session_id += 1
        self.animating = False
        self.clear()
        self.prepare_surface()
        canvas = tk.Canvas(self.container, highlightthickness=0)
        canvas.pack()
        self.draw_background(canvas)

        canvas.create_text(self.px(78), self.px(94), text="箭路突围", anchor="w", fill=ACCENT, font=self.ui_font(18, bold=True))
        canvas.create_text(self.px(78), self.px(154), text="每一步，都要看清方向", anchor="w", fill=TEXT, font=self.ui_font(30, bold=True))
        canvas.create_text(self.px(78), self.px(204), text="点击箭头，让它沿着自己的方向离开棋盘", anchor="w", fill=TEXT_MUTED, font=self.ui_font(14))

        left = tk.Frame(canvas, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        left.place(x=self.px(78), y=self.px(270), width=self.px(400), height=self.px(500))
        tk.Label(left, text="游戏目标", bg=PANEL_BG, fg=GOLD, font=self.ui_font(12, bold=True)).pack(anchor="w", padx=self.px(28), pady=(self.px(24), self.px(8)))
        tk.Label(left, text="清空棋盘上的所有箭头", wraplength=self.px(340), justify="left", bg=PANEL_BG, fg=TEXT, font=self.ui_font(16, bold=True)).pack(anchor="w", padx=self.px(28))
        tk.Label(left, text="如果箭头前方有其他箭头，它会被阻挡。\n每次误点都会消耗一次机会。", wraplength=self.px(330), justify="left", bg=PANEL_BG, fg=TEXT_MUTED, font=self.ui_font(11), pady=self.px(14)).pack(anchor="w", padx=self.px(28))
        tk.Label(left, text="5 个关卡  ·  棋盘逐步变大  ·  每关独立计时", bg=PANEL_BG, fg=TEXT_MUTED, font=self.ui_font(9)).pack(anchor="w", padx=self.px(28), pady=(self.px(6), 0))
        actions = tk.Frame(left, bg=PANEL_BG)
        actions.pack(fill="x", padx=self.px(28), pady=(self.px(16), self.px(16)))
        self.make_button(actions, "开始游戏", lambda: self.load_level(0), width=18).pack(pady=(0, self.px(10)))
        self.make_button(actions, "继续游戏", self.continue_saved_game, color=SECONDARY, width=18).pack(pady=(0, self.px(10)))
        self.make_button(actions, "选择关卡", self.show_level_select, color=SECONDARY, width=18).pack()

        preview = tk.Frame(canvas, bg=PANEL_LIGHT, highlightthickness=1, highlightbackground=BORDER)
        preview.place(x=self.px(540), y=self.px(270), width=self.px(380), height=self.px(500))
        tk.Label(preview, text="方向预览", bg=PANEL_LIGHT, fg=TEXT, font=self.ui_font(14, bold=True)).pack(anchor="w", padx=self.px(24), pady=(self.px(22), self.px(8)))
        demo = tk.Canvas(preview, width=self.px(330), height=self.px(235), bg=BOARD_BG, highlightthickness=1, highlightbackground=BORDER)
        demo.pack(padx=self.px(24), pady=self.px(5))
        self.draw_demo(demo)
        tk.Label(
            preview,
            text="箭头会沿自身方向离开棋盘，先观察前方是否有阻挡。",
            wraplength=self.px(320),
            justify="left",
            bg=PANEL_LIGHT,
            fg=TEXT_MUTED,
            font=self.ui_font(10),
        ).pack(anchor="w", padx=self.px(24), pady=(self.px(12), self.px(8)))
        direction_guide = tk.Frame(preview, bg=PANEL_LIGHT)
        direction_guide.pack(fill="x", padx=self.px(24), pady=(0, self.px(10)))
        for column, (symbol, name, direction) in enumerate((("↑", "向上", "U"), ("↓", "向下", "D"), ("←", "向左", "L"), ("→", "向右", "R"))):
            cell = tk.Frame(direction_guide, bg=ARROW_COLORS[direction], highlightthickness=1, highlightbackground="#ffffff")
            cell.grid(row=0, column=column, padx=(0 if column == 0 else self.px(5), 0), sticky="nsew")
            direction_guide.grid_columnconfigure(column, weight=1)
            tk.Label(cell, text=symbol, bg=ARROW_COLORS[direction], fg=INK, font=self.ui_font(16, bold=True)).pack(pady=0)
            tk.Label(cell, text=name, bg=ARROW_COLORS[direction], fg=INK, font=self.ui_font(8, bold=True)).pack(pady=(0, self.px(2)))

        canvas.create_text(self.px(78), self.px(812), text="快捷键：R 重开本关    H 查看提示    Esc 返回主菜单", anchor="w", fill=HELPER, font=self.ui_font(10))

    def continue_saved_game(self):
        saved = self.read_saved_progress()
        if saved is None:
            self.show_level_select()
            return
        next_level = saved.get("next_level")
        if isinstance(next_level, int) and 0 <= next_level < len(LEVELS):
            next_state = dict(saved)
            next_state["level_index"] = next_level
            next_state["active"] = []
            next_state["elapsed_seconds"] = 0
            next_state["moves"] = 0
            next_state["blocked_attempts"] = 0
            self.load_level(next_level, saved_state=next_state)
        else:
            self.load_level(saved["level_index"], saved_state=saved)

    def unlocked_level_count(self):
        saved = self.read_saved_progress()
        unlocked = getattr(self, "max_unlocked_level", 0)
        if saved:
            unlocked = max(unlocked, int(saved.get("max_unlocked_level", 0)))
            level_index = saved.get("level_index")
            if isinstance(level_index, int):
                unlocked = max(unlocked, level_index)
            next_level = saved.get("next_level")
            if isinstance(next_level, int):
                unlocked = max(unlocked, next_level)
        return min(len(LEVELS), unlocked + 1)

    def show_level_select(self):
        self.current_view = "level_select"
        self.session_id += 1
        self.animating = False
        self.clear()
        self.prepare_surface()
        canvas = tk.Canvas(self.container, highlightthickness=0)
        canvas.pack()
        self.draw_background(canvas)
        panel = tk.Frame(canvas, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        panel.place(x=self.px(220), y=self.px(85), width=self.px(560), height=self.px(730))
        tk.Label(panel, text="选择关卡", bg=PANEL_BG, fg=ACCENT, font=self.ui_font(25, bold=True)).pack(pady=(self.px(34), self.px(8)))
        tk.Label(panel, text="已解锁的关卡可以重复挑战", bg=PANEL_BG, fg=TEXT_MUTED, font=self.ui_font(11)).pack(pady=(0, self.px(22)))
        unlocked = self.unlocked_level_count()
        for index, level in enumerate(LEVELS):
            if index < unlocked:
                text = f"第 {index + 1} 关  ·  {level['name']}"
                color = ACCENT if index == 0 else SECONDARY
                button = self.make_button(panel, text, lambda i=index: self.load_level(i), color=color, width=24)
            else:
                button = self.make_button(panel, f"第 {index + 1} 关  ·  尚未解锁", lambda: None, color="#f1e4dc", width=24)
                button.configure(state="disabled", disabledforeground=TEXT_MUTED)
            button.pack(pady=self.px(6))
        self.make_button(panel, "返回主界面", self.show_start_screen, color=SECONDARY, width=18).pack(pady=(self.px(22), 0))

    def draw_demo(self, canvas):
        cell = self.px(52)
        for r in range(4):
            for c in range(5):
                x, y = self.px(18) + c * cell, self.px(18) + r * cell
                canvas.create_rectangle(x, y, x + cell - self.px(2), y + cell - self.px(2), fill=BOARD_BG, outline=GRID_LINE)
                canvas.create_oval(x + self.px(23), y + self.px(23), x + self.px(27), y + self.px(27), fill=GRID_DOT, outline="")
        for r, c, direction in [(0, 1, "R"), (1, 3, "D"), (2, 2, "U"), (3, 4, "L")]:
            x, y = self.px(18) + c * cell + self.px(25), self.px(18) + r * cell + self.px(25)
            canvas.create_oval(x - self.px(18), y - self.px(18), x + self.px(18), y + self.px(18), fill=ARROW_COLORS[direction], outline="#ffffff", width=self.px(2))
            canvas.create_polygon(self.arrow_points(x, y, direction, 0.7 * self.ui_scale), fill=INK, outline=INK)

    def load_level(self, index, preserve_state=False, saved_state=None):
        if not 0 <= index < len(LEVELS):
            return
        preserved = None
        if preserve_state:
            preserved = {
                "active": [arrow.active for arrow in self.arrows],
                "mistakes_left": self.mistakes_left,
                "moves": self.moves,
                "blocked_attempts": self.blocked_attempts,
                "elapsed_seconds": self.current_elapsed_seconds(),
                "level_scores": self.level_scores,
                "max_unlocked_level": self.max_unlocked_level,
            }
        elif saved_state is not None:
            preserved = saved_state
        self.session_id += 1
        self.clear()
        self.current_view = "game"
        self.prepare_surface()
        self.level_index = index
        level = LEVELS[index]
        self.arrows = [Arrow(a.row, a.col, a.direction) for a in level["arrows"]]
        self.mistakes_left = level["mistakes"]
        self.moves = 0
        self.blocked_attempts = 0
        self.elapsed_seconds = 0
        self.timer_started_at = time.monotonic()
        self.timer_text.set("00:00")
        if preserved is not None:
            for arrow, active in zip(self.arrows, preserved.get("active", [])):
                arrow.active = active
            # Older save files may contain the previous, larger mistake limit.
            self.mistakes_left = max(0, min(2, int(preserved.get("mistakes_left", self.mistakes_left))))
            self.moves = preserved.get("moves", self.moves)
            self.blocked_attempts = preserved.get("blocked_attempts", self.blocked_attempts)
            self.elapsed_seconds = preserved.get("elapsed_seconds", self.elapsed_seconds)
            self.timer_started_at = time.monotonic() - self.elapsed_seconds
            self.level_scores = {
                int(key): value for key, value in preserved.get("level_scores", {}).items()
            }
            self.max_unlocked_level = max(
                self.max_unlocked_level,
                int(preserved.get("max_unlocked_level", index)),
            )
            minutes, seconds = divmod(self.elapsed_seconds, 60)
            self.timer_text.set(f"{minutes:02d}:{seconds:02d}")
        elif index == 0:
            self.level_scores = {}
        self.max_unlocked_level = max(getattr(self, "max_unlocked_level", 0), index)
        self.animating = False
        self.hover_index = None
        self.arrow_items = {}
        base_cell_size = min(66, max(52, (WINDOW_HEIGHT - 310) // max(level["rows"], level["cols"])))
        self.cell_size = self.px(base_cell_size)

        header = tk.Frame(self.container, bg=WINDOW_BG, padx=self.px(44), pady=self.px(14))
        header.pack(fill="x")
        tk.Label(header, text="箭路突围", bg=WINDOW_BG, fg=ACCENT, font=self.ui_font(16, bold=True)).pack(side="left")
        tk.Label(header, text=f"  /  第 {index + 1} 关 · {level['name']}", bg=WINDOW_BG, fg=TEXT_MUTED, font=self.ui_font(13, bold=True)).pack(side="left")
        self.make_button(header, "主菜单", self.return_to_menu, color=SECONDARY, width=8).pack(side="right")
        self.make_button(header, "保存", self.save_and_notify, color=SECONDARY, width=7).pack(side="right", padx=self.px(6))
        self.make_button(header, "重新开始", self.restart_level, color=SECONDARY, width=9).pack(side="right", padx=self.px(6))
        self.make_button(header, "提示", self.show_hint, color=SECONDARY, width=7).pack(side="right")

        stats = tk.Frame(self.container, bg=WINDOW_BG, padx=self.px(44))
        stats.pack(fill="x")
        self.stat_remaining = self.add_stat(stats, "剩余箭头", "")
        self.stat_lives = self.add_stat(stats, "剩余机会", "")
        self.stat_moves = self.add_stat(stats, "操作步数", "")
        self.stat_timer = self.add_stat(stats, "本关用时", "")
        self.stat_level = self.add_stat(stats, "关卡进度", "")

        board_w = level["cols"] * self.cell_size + self.px(PADDING) * 2
        board_h = level["rows"] * self.cell_size + self.px(PADDING) * 2
        game_area = tk.Frame(self.container, bg=WINDOW_BG)
        game_area.pack(fill="both", expand=True, pady=self.px(16), padx=self.px(44))
        board_holder = tk.Frame(game_area, bg=WINDOW_BG)
        board_holder.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(board_holder, width=board_w, height=board_h, bg=BOARD_BG, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.place(relx=0.5, rely=0.5, anchor="center")
        self.canvas.bind("<Button-1>", self.handle_click)
        self.canvas.bind("<Motion>", self.handle_motion)
        self.canvas.bind("<Leave>", lambda _e: self.set_hover(None))
        ai_panel = tk.Frame(game_area, bg=PANEL_LIGHT, width=self.px(214), highlightthickness=1, highlightbackground=BORDER)
        ai_panel.pack(side="right", fill="y", padx=(self.px(18), 0))
        ai_panel.pack_propagate(False)
        tk.Label(ai_panel, text="AI 助手", bg=PANEL_LIGHT, fg=TEXT, font=self.ui_font(14, bold=True)).pack(anchor="w", padx=self.px(18), pady=(self.px(22), self.px(8)))
        tk.Label(
            ai_panel,
            text="AI 会寻找当前可行的箭头，逐步完成本关。",
            wraplength=self.px(178),
            justify="left",
            bg=PANEL_LIGHT,
            fg=TEXT_MUTED,
            font=self.ui_font(10),
        ).pack(anchor="w", padx=self.px(18), pady=(0, self.px(18)))
        self.ai_button = self.make_button(ai_panel, "AI 一键逐步求解", self.toggle_ai_solver, width=12)
        self.ai_button.pack(padx=self.px(12), pady=(0, self.px(18)))
        tk.Label(ai_panel, textvariable=self.ai_status, bg=PANEL_LIGHT, fg=ACCENT, font=self.ui_font(10, bold=True), wraplength=self.px(178), justify="left").pack(anchor="w", padx=self.px(18))
        tk.Label(ai_panel, text="AI 操作不会消耗误点次数。", bg=PANEL_LIGHT, fg=HELPER, font=self.ui_font(9), wraplength=self.px(178), justify="left").pack(anchor="w", padx=self.px(18), pady=(self.px(18), 0))
        tk.Label(self.container, textvariable=self.message, bg=WINDOW_BG, fg=TEXT_MUTED, font=self.ui_font(11)).pack(pady=(0, self.px(6)))
        tk.Label(self.container, text="沿箭头方向前方没有阻挡时，点击它即可离开", bg=WINDOW_BG, fg=HELPER, font=self.ui_font(9)).pack()
        self.draw_board()
        self.update_status("寻找一条没有阻挡的路线。")
        self.tick_timer()

    def add_stat(self, parent, title, value):
        box = tk.Frame(parent, bg=PANEL_BG, padx=self.px(12), pady=self.px(8), highlightthickness=1, highlightbackground=BORDER)
        box.pack(side="left", fill="x", expand=True, padx=(0, self.px(8)))
        tk.Label(box, text=title, bg=PANEL_BG, fg=TEXT_MUTED, font=self.ui_font(9, bold=True)).pack(anchor="w")
        label = tk.Label(box, text=value, bg=PANEL_BG, fg=TEXT, font=self.ui_font(14, bold=True))
        label.pack(anchor="w")
        return label

    def tick_timer(self):
        if self.current_view != "game" or not self.arrows or self.session_id <= 0:
            return
        self.elapsed_seconds = self.current_elapsed_seconds()
        minutes, seconds = divmod(self.elapsed_seconds, 60)
        self.timer_text.set(f"{minutes:02d}:{seconds:02d}")
        if hasattr(self, "stat_timer"):
            self.stat_timer.config(text=self.timer_text.get())
        self.timer_id = self.root.after(200, self.tick_timer)

    def save_and_notify(self):
        if self.save_progress():
            self.update_status("进度已保存，可以从主界面继续游戏。")
        else:
            self.update_status("进度保存失败，请检查文件夹权限。")

    def return_to_menu(self):
        self.save_progress()
        self.show_start_screen()

    def draw_board(self):
        self.canvas.delete("all")
        level = LEVELS[self.level_index]
        for r in range(level["rows"]):
            for c in range(level["cols"]):
                x1, y1 = self.cell_origin(r, c)
                self.canvas.create_rectangle(x1, y1, x1 + self.cell_size, y1 + self.cell_size, fill=BOARD_BG, outline=GRID_LINE)
                dot = self.px(2)
                self.canvas.create_oval(x1 + self.cell_size / 2 - dot, y1 + self.cell_size / 2 - dot, x1 + self.cell_size / 2 + dot, y1 + self.cell_size / 2 + dot, fill=GRID_DOT, outline="")
        self.arrow_items.clear()
        for index, arrow in enumerate(self.arrows):
            if arrow.active:
                self.draw_arrow(index, arrow)

    def draw_arrow(self, index, arrow):
        x, y = self.cell_center(arrow.row, arrow.col)
        tag = f"arrow_{index}"
        color = ARROW_COLORS[arrow.direction]
        radius = self.px(22)
        circle = self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="#ffffff", width=self.px(2), tags=(tag,))
        symbol = self.canvas.create_polygon(self.arrow_points(x, y, arrow.direction, self.ui_scale), fill=INK, outline=INK, tags=(tag,))
        self.arrow_items[index] = (circle, symbol)

    def arrow_points(self, x, y, direction, scale=1.0):
        base = [(0, -19), (-9, -6), (-4, -6), (-4, 15), (4, 15), (4, -6), (9, -6)]
        if direction == "U":
            transformed = base
        elif direction == "D":
            transformed = [(px, -py) for px, py in base]
        elif direction == "L":
            transformed = [(py, px) for px, py in base]
        else:
            transformed = [(-py, px) for px, py in base]
        return [coordinate for px, py in transformed for coordinate in (x + px * scale, y + py * scale)]

    def cell_origin(self, row, col):
        padding = self.px(PADDING)
        return padding + col * self.cell_size, padding + row * self.cell_size

    def cell_center(self, row, col):
        x1, y1 = self.cell_origin(row, col)
        return x1 + self.cell_size / 2, y1 + self.cell_size / 2

    def update_status(self, text):
        active = sum(1 for arrow in self.arrows if arrow.active)
        self.stat_remaining.config(text=f"{active:02d}")
        self.stat_lives.config(text=f"{self.mistakes_left:02d}", fg=DANGER if self.mistakes_left <= 2 else TEXT)
        self.stat_moves.config(text=f"{self.moves:02d}")
        self.stat_timer.config(text=self.timer_text.get())
        self.stat_level.config(text=f"{self.level_index + 1} / {len(LEVELS)}")
        self.message.set(text)

    def handle_motion(self, event):
        if not self.animating:
            self.set_hover(self.find_arrow_at(event.x, event.y))

    def set_hover(self, index):
        if index == self.hover_index:
            return
        old = self.hover_index
        self.hover_index = index
        for item_index in [old, index]:
            if item_index is not None and item_index in self.arrow_items:
                circle, _symbol = self.arrow_items[item_index]
                self.canvas.itemconfig(circle, outline=TEXT if item_index == index else "#ffffff", width=self.px(4 if item_index == index else 2))
        self.canvas.configure(cursor="hand2" if index is not None else "")

    def handle_click(self, event):
        if self.animating or self.ai_solving:
            return
        clicked = self.find_arrow_at(event.x, event.y)
        if clicked is None:
            self.update_status("请点击棋盘上的箭头。")
            return
        self.moves += 1
        blocker = self.find_blocker(clicked)
        if blocker is None:
            self.fly_out(clicked)
        else:
            self.block_arrow(clicked, blocker)

    def find_arrow_at(self, x, y):
        for index, arrow in enumerate(self.arrows):
            if not arrow.active:
                continue
            cx, cy = self.cell_center(arrow.row, arrow.col)
            if (x - cx) ** 2 + (y - cy) ** 2 <= self.px(27) ** 2:
                return index
        return None

    def find_blocker(self, index):
        level = LEVELS[self.level_index]
        return find_blocker_in_state(self.arrows, level["rows"], level["cols"], index)

    def fly_out(self, index):
        self.animating = True
        play_sound("fly")
        session_id = self.session_id
        arrow = self.arrows[index]
        dr, dc, _ = DIRECTIONS[arrow.direction]
        items = self.arrow_items[index]
        distance = max(LEVELS[self.level_index]["rows"], LEVELS[self.level_index]["cols"]) * self.cell_size
        frames = 28

        def step(frame):
            if session_id != self.session_id:
                return
            if frame <= frames:
                eased = 1 - (1 - frame / frames) ** 3
                previous = 1 - (1 - max(0, frame - 1) / frames) ** 3
                delta = eased - previous
                for item in items:
                    self.canvas.move(item, dc * distance * delta, dr * distance * delta)
                self.root.after(16, lambda: step(frame + 1))
            else:
                for item in items:
                    self.canvas.delete(item)
                arrow.active = False
                self.animating = False
                self.after_arrow_removed()

        self.update_status("箭头正在沿路线飞出。")
        step(0)

    def block_arrow(self, index, blocker):
        self.animating = True
        play_sound("collision")
        self.blocked_attempts += 1
        self.mistakes_left -= 1
        session_id = self.session_id
        circle, symbol = self.arrow_items[index]
        blocker_circle, blocker_symbol = self.arrow_items[blocker]
        self.canvas.itemconfig(circle, fill=DANGER, outline="#fff0f2", width=4)
        self.canvas.itemconfig(symbol, fill="#ffffff", outline="#ffffff")
        self.canvas.itemconfig(blocker_circle, fill="#c7ffe9", outline=GOLD, width=4)
        self.canvas.itemconfig(blocker_symbol, fill=INK, outline=INK)
        self.draw_collision_feedback(index, blocker, session_id)
        self.update_status("箭头被挡住了，请先处理前方高亮箭头。")
        self.animate_collision_feedback(index, blocker, session_id, 0)

    def draw_collision_feedback(self, index, blocker, session_id):
        clicked_x, clicked_y = self.cell_center(self.arrows[index].row, self.arrows[index].col)
        blocker_x, blocker_y = self.cell_center(self.arrows[blocker].row, self.arrows[blocker].col)
        tag = f"collision_{session_id}"
        self.canvas.create_line(
            clicked_x, clicked_y, blocker_x, blocker_y,
            fill="#e7ad70", width=self.px(4), dash=(self.px(8), self.px(5)), tags=(tag, "collision_path"),
        )
        for x, y, color in ((clicked_x, clicked_y, DANGER), (blocker_x, blocker_y, GOLD)):
            radius = self.cell_size * 0.38
            self.canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                outline=color, width=self.px(3), tags=(tag, "collision_ring"),
            )
        ray_length = self.cell_size * 0.30
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            self.canvas.create_line(
                clicked_x + dx * ray_length * 0.55,
                clicked_y + dy * ray_length * 0.55,
                clicked_x + dx * ray_length,
                clicked_y + dy * ray_length,
                fill=DANGER, width=self.px(3), tags=(tag, "collision_ray"),
            )
        self.canvas.tag_lower(tag)
        for item_index in (index, blocker):
            if item_index in self.arrow_items:
                circle, symbol = self.arrow_items[item_index]
                self.canvas.tag_raise(circle)
                self.canvas.tag_raise(symbol)

    def animate_collision_feedback(self, index, blocker, session_id, frame):
        if session_id != self.session_id:
            return
        if frame < 8:
            offset = 3 if frame % 2 == 0 else -3
            for item_index in (index, blocker):
                if item_index in self.arrow_items:
                    for item in self.arrow_items[item_index]:
                        self.canvas.move(item, offset, 0)
            pulse_width = 5 if frame % 2 == 0 else 3
            for item_index in (index, blocker):
                if item_index in self.arrow_items:
                    circle, _symbol = self.arrow_items[item_index]
                    self.canvas.itemconfig(circle, width=pulse_width)
            self.root.after(45, lambda: self.animate_collision_feedback(index, blocker, session_id, frame + 1))
            return
        self.root.after(120, lambda: self.finish_block_feedback(index, blocker, session_id))

    def finish_block_feedback(self, index, blocker, session_id):
        if session_id != self.session_id:
            return
        self.canvas.delete(f"collision_{session_id}")
        if index in self.arrow_items and self.arrows[index].active:
            circle, symbol = self.arrow_items[index]
            self.canvas.itemconfig(circle, fill=ARROW_COLORS[self.arrows[index].direction], outline="#ffffff", width=2)
            self.canvas.itemconfig(symbol, fill=INK, outline=INK)
        if blocker in self.arrow_items and self.arrows[blocker].active:
            circle, symbol = self.arrow_items[blocker]
            self.canvas.itemconfig(circle, fill=ARROW_COLORS[self.arrows[blocker].direction], outline="#ffffff", width=2)
            self.canvas.itemconfig(symbol, fill=INK, outline=INK)
        self.animating = False
        if self.mistakes_left <= 0:
            self.show_result(False)
        else:
            self.update_status("路线被挡住了，请调整点击顺序。")

    def after_arrow_removed(self):
        if all(not arrow.active for arrow in self.arrows):
            self.elapsed_seconds = self.current_elapsed_seconds()
            score = calculate_level_score(self.level_index, self.elapsed_seconds, self.blocked_attempts)
            self.level_scores[self.level_index] = score
            if self.level_index == len(LEVELS) - 1:
                self.clear_saved_progress()
                self.show_result(True)
            else:
                self.max_unlocked_level = max(self.max_unlocked_level, self.level_index + 1)
                self.save_progress(next_level=self.level_index + 1)
                self.show_level_clear()
        else:
            if self.ai_solving:
                self.ai_step += 1
                self.ai_status.set(f"正在求解：已完成 {self.ai_step} 步")
                self.ai_after_id = self.root.after(160, self.ai_solve_step)
            else:
                self.update_status("不错，棋盘正在逐步打开。")

    def show_level_clear(self):
        if self.current_view != "level_clear":
            play_sound("win")
        self.current_view = "level_clear"
        self.session_id += 1
        self.animating = False
        self.clear()
        self.prepare_surface()
        canvas = tk.Canvas(self.container, highlightthickness=0)
        canvas.pack()
        self.draw_background(canvas)
        panel = tk.Frame(canvas, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        panel.place(x=self.px(220), y=self.px(55), width=self.px(560), height=self.px(790))
        score = self.level_scores.get(
            self.level_index,
            calculate_level_score(self.level_index, self.elapsed_seconds, self.blocked_attempts),
        )
        tk.Label(panel, text="本关完成", bg=PANEL_BG, fg=ACCENT, font=self.ui_font(17, bold=True)).pack(pady=(self.px(38), self.px(10)))
        tk.Label(panel, text=f"第 {self.level_index + 1} 关 · {LEVELS[self.level_index]['name']}", bg=PANEL_BG, fg=TEXT, font=self.ui_font(25, bold=True)).pack()
        tk.Label(panel, text=LEVELS[self.level_index]["subtitle"], bg=PANEL_BG, fg=TEXT_MUTED, font=self.ui_font(12)).pack(pady=(self.px(8), self.px(20)))
        tk.Label(panel, text=f"用时 {self.timer_text.get()}    ·    步数 {self.moves}    ·    误点 {self.blocked_attempts}", bg=PANEL_BG, fg=GOLD, font=self.ui_font(12, bold=True)).pack(pady=(0, self.px(25)))
        tk.Label(panel, text=f"本关评分  {score_grade(score)}  ·  {score} 分", bg=PANEL_BG, fg=ACCENT, font=self.ui_font(16, bold=True)).pack(pady=(0, self.px(8)))
        image_holder = tk.Frame(panel, bg=PANEL_BG)
        image_holder.pack(pady=(0, self.px(14)))
        self.result_frames = self.fit_result_frames(self.load_result_image(True))
        if self.result_frames:
            self.result_image_label = tk.Label(image_holder, image=self.result_frames[0], bg=PANEL_BG)
            self.result_image_label.pack()
            self.start_result_frame_playback()
        else:
            self.result_image_label = None
        self.make_button(panel, "进入下一关", lambda: self.load_level(self.level_index + 1), width=18).pack()
        self.make_button(panel, "返回主界面", self.show_start_screen, color=SECONDARY, width=18).pack(pady=self.px(10))

    def load_result_image(self, passed):
        """Load the celebration / defeat image as frames.

        Pillow composites GIF disposal/transparency rules before Tk sees a
        frame. Directly loading GIF subframes through PhotoImage would show
        only changed pixels for delta-encoded animations.
        """
        name = WIN_IMAGE_NAME if passed else FAIL_IMAGE_NAME
        for extension in (".gif", ".png"):
            path = os.path.join(ASSET_DIR, name + extension)
            if not os.path.exists(path):
                continue
            try:
                with Image.open(path) as source:
                    frame_count = getattr(source, "n_frames", 1)
                    frames = []
                    delays = []
                    for index in range(frame_count):
                        source.seek(index)
                        frames.append(source.convert("RGBA").copy())
                        delays.append(max(40, int(source.info.get("duration", 100) or 100)))
                    self.result_frame_delays = delays
                    return frames
            except (OSError, ValueError):
                self.result_frame_delays = []
                return []
        return []

    def fit_result_frames(self, frames):
        """Scale composited frames into RESULT_IMAGE_BOX with high quality."""
        if not frames:
            return frames
        box_w, box_h = (self.px(value) for value in RESULT_IMAGE_BOX)
        width, height = frames[0].size
        scale = min(box_w / width, box_h / height)
        target_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        return [
            ImageTk.PhotoImage(
                frame.resize(target_size, Image.Resampling.LANCZOS),
                master=self.root,
            )
            for frame in frames
        ]

    def start_result_frame_playback(self):
        if len(self.result_frames) < 2 or self.result_image_label is None:
            return
        self.result_frame_index = 0
        self._advance_result_frame()

    def _advance_result_frame(self):
        if self.result_image_label is None or not self.result_frames:
            return
        frame = self.result_frames[self.result_frame_index % len(self.result_frames)]
        self.result_image_label.configure(image=frame)
        frame_index = self.result_frame_index % len(self.result_frames)
        self.result_frame_index += 1
        delay = RESULT_FRAME_DELAY_MS
        if frame_index < len(self.result_frame_delays):
            delay = self.result_frame_delays[frame_index]
        self.result_frame_job = self.root.after(delay, self._advance_result_frame)

    def stop_result_frame_playback(self):
        if self.result_frame_job is not None:
            self.root.after_cancel(self.result_frame_job)
            self.result_frame_job = None
        self.result_frames = []
        self.result_frame_index = 0
        self.result_image_label = None
        self.result_frame_delays = []

    def show_result(self, passed):
        if self.current_view != "result" or self.result_passed != passed:
            play_sound("win" if passed else "fail")
        self.current_view = "result"
        self.result_passed = passed
        self.session_id += 1
        self.animating = False
        self.clear()
        self.prepare_surface()
        canvas = tk.Canvas(self.container, highlightthickness=0)
        canvas.pack()
        self.draw_background(canvas)
        panel = tk.Frame(canvas, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        panel.place(x=self.px(220), y=self.px(60), width=self.px(560), height=self.px(780))
        title = "全部通关" if passed else "挑战结束"
        color = ACCENT if passed else DANGER
        detail = "你已经清空全部棋盘，完成了挑战。" if passed else "机会用尽了，重新规划路线再试一次。"
        total_score = sum(self.level_scores.values())
        final_score = self.level_scores.get(
            self.level_index,
            calculate_level_score(self.level_index, self.elapsed_seconds, self.blocked_attempts),
        )
        tk.Label(panel, text=title, bg=PANEL_BG, fg=color, font=self.ui_font(18, bold=True)).pack(pady=(self.px(26), self.px(8)))
        tk.Label(panel, text="箭路突围", bg=PANEL_BG, fg=TEXT, font=self.ui_font(28, bold=True)).pack()
        tk.Label(panel, text=detail, bg=PANEL_BG, fg=TEXT_MUTED, font=self.ui_font(12)).pack(pady=(self.px(10), self.px(16)))
        tk.Label(panel, text=f"总步数 {self.moves}    ·    总误点 {self.blocked_attempts}    ·    最后一关用时 {self.timer_text.get()}", bg=PANEL_BG, fg=GOLD, font=self.ui_font(11, bold=True)).pack(pady=(0, self.px(10)))
        if passed:
            tk.Label(panel, text=f"本关评分  {score_grade(final_score)}  ·  {final_score} 分", bg=PANEL_BG, fg=ACCENT, font=self.ui_font(14, bold=True)).pack(pady=(0, self.px(6)))
            tk.Label(panel, text=f"总评分  {total_score} / {len(LEVELS) * 1000}", bg=PANEL_BG, fg=ACCENT, font=self.ui_font(14, bold=True)).pack(pady=(0, self.px(10)))
        image_holder = tk.Frame(panel, bg=PANEL_BG)
        image_holder.pack(pady=(self.px(2), self.px(14)))
        self.result_frames = self.fit_result_frames(self.load_result_image(passed))
        if self.result_frames:
            self.result_image_label = tk.Label(image_holder, image=self.result_frames[0], bg=PANEL_BG)
            self.result_image_label.pack()
            self.start_result_frame_playback()
        else:
            self.result_image_label = None
        self.make_button(panel, "重新挑战", lambda: self.load_level(0), width=18).pack()
        self.make_button(panel, "返回主界面", self.show_start_screen, color=SECONDARY, width=18).pack(pady=self.px(10))

    def restart_level(self):
        self.load_level(self.level_index)

    def toggle_ai_solver(self):
        if self.current_view != "game" or not self.arrows:
            return
        if self.ai_solving:
            self.ai_solving = False
            if self.ai_after_id is not None:
                self.root.after_cancel(self.ai_after_id)
                self.ai_after_id = None
            self.ai_status.set("已暂停，可以继续手动操作")
            if self.ai_button is not None:
                self.ai_button.configure(text="AI 一键逐步求解")
            return
        self.ai_solving = True
        self.ai_step = 0
        self.ai_status.set("正在分析当前棋盘...")
        if self.ai_button is not None:
            self.ai_button.configure(text="暂停 AI 求解")
        self.ai_solve_step()

    def ai_solve_step(self):
        self.ai_after_id = None
        if not self.ai_solving or self.current_view != "game" or self.animating:
            return
        index = next(
            (
                index
                for index, arrow in enumerate(self.arrows)
                if arrow.active and self.find_blocker(index) is None
            ),
            None,
        )
        if index is None:
            self.ai_solving = False
            self.ai_status.set("当前布局没有可行步骤")
            if self.ai_button is not None:
                self.ai_button.configure(text="AI 一键逐步求解")
            return
        circle, symbol = self.arrow_items[index]
        self.canvas.itemconfig(circle, fill="#c7ffe9", outline=ACCENT, width=4)
        self.canvas.itemconfig(symbol, fill="#527461", outline="#527461")
        self.ai_status.set(f"第 {self.ai_step + 1} 步：找到可移出的箭头")
        self.root.after(260, lambda i=index, sid=self.session_id: self.ai_execute_step(i, sid))

    def ai_execute_step(self, index, session_id):
        if session_id != self.session_id or not self.ai_solving or self.current_view != "game":
            return
        if index >= len(self.arrows) or not self.arrows[index].active or self.find_blocker(index) is not None:
            self.ai_solve_step()
            return
        self.moves += 1
        self.fly_out(index)

    def show_hint(self):
        if self.animating or not self.arrows:
            return
        session_id = self.session_id
        for index, arrow in enumerate(self.arrows):
            if arrow.active and self.find_blocker(index) is None:
                circle, symbol = self.arrow_items[index]
                self.canvas.itemconfig(circle, fill="#c7ffe9", outline=ACCENT, width=4)
                self.canvas.itemconfig(symbol, fill="#527461", outline="#527461")
                self.root.after(650, lambda i=index, sid=session_id: self.restore_hint(i, sid))
                self.update_status("提示：这个箭头前方没有阻挡。")
                return
        self.update_status("暂时没有可直接离开的箭头。")

    def restore_hint(self, index, session_id):
        if session_id != self.session_id:
            return
        if index in self.arrow_items and self.arrows[index].active:
            circle, symbol = self.arrow_items[index]
            self.canvas.itemconfig(circle, fill=ARROW_COLORS[self.arrows[index].direction], outline="#ffffff", width=2)
            self.canvas.itemconfig(symbol, fill=INK, outline=INK)


if __name__ == "__main__":
    enable_high_dpi()
    app = tk.Tk()
    ArrowEscapeGame(app)
    app.mainloop()
