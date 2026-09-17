import unittest

from main import (
    Arrow,
    DIRECTIONS,
    LEVELS,
    calculate_level_score,
    find_clear_order,
    find_blocker_in_state,
    line_direction_stats,
)


class ArrowGameLogicTests(unittest.TestCase):
    def test_edge_arrow_can_leave_board(self):
        arrows = [Arrow(0, 0, "U")]
        self.assertIsNone(find_blocker_in_state(arrows, 1, 1, 0))

    def test_arrow_detects_blocker_in_same_direction(self):
        arrows = [
            Arrow(1, 0, "R"),
            Arrow(1, 2, "U"),
        ]
        self.assertEqual(find_blocker_in_state(arrows, 3, 3, 0), 1)

    def test_inactive_arrow_does_not_block(self):
        arrows = [
            Arrow(1, 0, "R"),
            Arrow(1, 2, "L", active=False),
        ]
        self.assertIsNone(find_blocker_in_state(arrows, 3, 3, 0))

    def test_all_directions_are_defined(self):
        self.assertEqual(set(DIRECTIONS), {"U", "D", "L", "R"})

    def test_each_level_allows_two_mistakes(self):
        self.assertEqual({level["mistakes"] for level in LEVELS}, {2})

    def test_horizontal_directions_use_correct_movement(self):
        self.assertEqual(DIRECTIONS["L"][:2], (0, -1))
        self.assertEqual(DIRECTIONS["R"][:2], (0, 1))

    def test_levels_have_meaningful_blockers(self):
        for level in LEVELS:
            arrows = [Arrow(a.row, a.col, a.direction) for a in level["arrows"]]
            blocked = sum(
                find_blocker_in_state(arrows, level["rows"], level["cols"], index) is not None
                for index in range(len(arrows))
            )
            self.assertGreaterEqual(blocked, 2, level["name"])

    def test_all_levels_have_a_clearable_order(self):
        for level in LEVELS:
            arrows = [Arrow(a.row, a.col, a.direction) for a in level["arrows"]]
            cleared = 0
            while cleared < len(arrows):
                removable = next(
                    (
                        index
                        for index, arrow in enumerate(arrows)
                        if arrow.active
                        and find_blocker_in_state(
                            arrows, level["rows"], level["cols"], index
                        )
                        is None
                    ),
                    None,
                )
                self.assertIsNotNone(removable, f"{level['name']} contains a deadlock")
                arrows[removable].active = False
                cleared += 1

    def test_ai_order_does_not_change_board_state(self):
        level = LEVELS[2]
        arrows = [Arrow(a.row, a.col, a.direction) for a in level["arrows"]]
        before = [arrow.active for arrow in arrows]
        order = find_clear_order(arrows, level["rows"], level["cols"])
        self.assertIsNotNone(order)
        self.assertEqual(before, [arrow.active for arrow in arrows])
        self.assertEqual(len(order), len(arrows))

    def test_score_rewards_fast_clean_clear(self):
        for index, level in enumerate(LEVELS):
            clean = calculate_level_score(index, level["par_time"], 0)
            slow = calculate_level_score(index, level["par_time"] + 30, 0)
            mistaken = calculate_level_score(index, level["par_time"], 2)
            self.assertGreater(clean, slow, level["name"])
            self.assertGreater(clean, mistaken, level["name"])
            self.assertGreaterEqual(clean, 0)
            self.assertLessEqual(clean, 1000)

    def test_later_levels_are_denser(self):
        for previous, current in zip(LEVELS, LEVELS[1:]):
            self.assertGreater(len(current["arrows"]), len(previous["arrows"]))

    def test_random_levels_use_all_directions(self):
        for level in LEVELS[1:]:
            directions = {arrow.direction for arrow in level["arrows"]}
            self.assertEqual(directions, set(DIRECTIONS), level["name"])

    def test_random_levels_are_not_regular_full_rows(self):
        for level in LEVELS[1:]:
            row_counts = {}
            for arrow in level["arrows"]:
                row_counts[arrow.row] = row_counts.get(arrow.row, 0) + 1
            self.assertLess(max(row_counts.values()), level["cols"], level["name"])

    def test_random_levels_avoid_long_adjacent_direction_runs(self):
        for level in LEVELS[1:]:
            max_run, _repeated_pairs = line_direction_stats(level["arrows"])
            self.assertLessEqual(max_run, 2, level["name"])


if __name__ == "__main__":
    unittest.main()
