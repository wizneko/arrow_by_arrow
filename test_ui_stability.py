"""界面稳定性测试：检查空闲状态下界面是否被反复重建（表现为闪烁）。"""

import unittest

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None

from main import WINDOW_HEIGHT, WINDOW_WIDTH, ArrowEscapeGame


IDLE_HOLD_MS = 1200
MAX_ALLOWED_REBUILDS = 1


class UiStabilityTests(unittest.TestCase):
    def setUp(self):
        if tk is None:
            self.skipTest("tkinter 不可用")
        try:
            self.root = tk.Tk()
        except tk.TclError as error:  # pragma: no cover
            self.skipTest(f"没有可用的显示环境: {error}")
        self.addCleanup(self._close_root)

    def _close_root(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _teardown_game(self, game):
        """Cancel pending callbacks before the window goes away."""
        if game.timer_id is not None:
            self.root.after_cancel(game.timer_id)
            game.timer_id = None
        if game.resize_after_id is not None:
            self.root.after_cancel(game.resize_after_id)
            game.resize_after_id = None

    def _count_rebuilds(self, enter_game):
        """让界面空闲一段时间，统计 start / load_level 被重复调用的次数。"""
        counts = {"start": 0, "load": 0}
        try:
            game = ArrowEscapeGame(self.root)
        except tk.TclError as error:  # pragma: no cover
            self.skipTest(f"无法创建游戏窗口: {error}")

        original_start = game.show_start_screen
        original_load = game.load_level

        def counting_start():
            counts["start"] += 1
            return original_start()

        def counting_load(index, preserve_state=False):
            counts["load"] += 1
            return original_load(index, preserve_state=preserve_state)

        game.show_start_screen = counting_start
        game.load_level = counting_load

        if enter_game:
            game.load_level(0)

        def finish():
            self._teardown_game(game)
            self.root.destroy()

        self.root.after(IDLE_HOLD_MS, finish)
        try:
            self.root.mainloop()
        except tk.TclError:  # pragma: no cover
            pass
        return counts

    def test_start_screen_is_not_rebuilt_while_idle(self):
        counts = self._count_rebuilds(enter_game=False)
        self.assertLessEqual(
            counts["start"],
            MAX_ALLOWED_REBUILDS,
            f"主界面在空闲 {IDLE_HOLD_MS}ms 内被重建 {counts['start']} 次，会持续闪烁",
        )

    def test_game_screen_is_not_rebuilt_while_idle(self):
        counts = self._count_rebuilds(enter_game=True)
        self.assertLessEqual(
            counts["load"],
            MAX_ALLOWED_REBUILDS + 1,  # 允许测试自身主动加载一次关卡
            f"游戏界面在空闲 {IDLE_HOLD_MS}ms 内被重建 {counts['load']} 次，会持续闪烁",
        )


    def test_real_window_resize_still_triggers_one_refresh(self):
        """A genuine toplevel size change must still rebuild the layout once."""
        try:
            game = ArrowEscapeGame(self.root)
        except tk.TclError as error:  # pragma: no cover
            self.skipTest(f"无法创建游戏窗口: {error}")

        counts = {"start": 0}
        original_start = game.show_start_screen

        def counting_start():
            counts["start"] += 1
            return original_start()

        game.show_start_screen = counting_start

        self.root.update_idletasks()
        self.root.update()

        baseline = counts["start"]
        current = self.root.winfo_width()
        self.root.geometry(f"{current + 120}x{WINDOW_HEIGHT}")

        self.root.after(IDLE_HOLD_MS, self.root.destroy)
        try:
            self.root.mainloop()
        except tk.TclError:  # pragma: no cover
            pass

        self._teardown_game(game)
        self.assertEqual(
            counts["start"] - baseline,
            1,
            "窗口尺寸真实变化后界面应重排一次，缩放响应不能被一并禁用",
        )

    def test_normal_window_keeps_original_layout_scale(self):
        game = ArrowEscapeGame(self.root)
        self.root.geometry("1400x1000")
        self.root.update_idletasks()
        self.root.update()
        game.prepare_surface()
        self.assertEqual(game.ui_scale, 1.0)
        self._teardown_game(game)

    def test_fullscreen_layout_scales_and_stays_centered(self):
        game = ArrowEscapeGame(self.root)
        self.root.geometry("1600x1000")
        self.root.update_idletasks()
        self.root.update()
        game.fullscreen = True
        game.prepare_surface()
        expected = min(1600 / WINDOW_WIDTH, 1000 / WINDOW_HEIGHT)
        self.assertAlmostEqual(game.ui_scale, expected, places=2)
        self.assertEqual(game.container.winfo_manager(), "place")
        self.assertEqual(game.container.place_info()["relx"], "0.5")
        self.assertEqual(game.container.place_info()["rely"], "0.5")
        self._teardown_game(game)


if __name__ == "__main__":
    unittest.main()
