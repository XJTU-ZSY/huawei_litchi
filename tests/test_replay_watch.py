import unittest
from pathlib import Path

from litchi_bot.replay_watch import build_replay_report, build_requirement_cards, is_stable, ReplayCandidate


class ReplayWatchTest(unittest.TestCase):
    def test_builds_p0_card_for_rejected_actions(self):
        summary = {
            "messageCount": 3,
            "rejectedCount": 1,
            "invalidCount": 0,
            "scores": {},
            "deliveries": {},
            "windowCards": {},
            "finalPlayers": {},
            "latestPlayers": {},
        }

        cards = build_requirement_cards(Path("match.json"), summary, player_id=1001)

        self.assertEqual(cards[0].priority, "P0")
        self.assertIn("拒绝/非法动作", cards[0].title)

    def test_builds_task90_card_when_task_score_is_low(self):
        summary = {
            "messageCount": 3,
            "rejectedCount": 0,
            "invalidCount": 0,
            "scores": {"1001": 120},
            "deliveries": {"1001": {"round": 500}},
            "windowCards": {},
            "finalPlayers": {"1001": {"playerId": 1001, "delivered": True, "taskScore": 60}},
            "latestPlayers": {},
        }

        cards = build_requirement_cards(Path("match.json"), summary, player_id=1001)

        self.assertTrue(any(card.priority == "P1" and "90" in card.title for card in cards))

    def test_report_uses_skill_report_sections(self):
        summary = {
            "messageCount": 1,
            "rejectedCount": 0,
            "invalidCount": 0,
            "scores": {},
            "deliveries": {},
            "windowCards": {"BING_ZHENG": 2},
            "finalPlayers": {},
            "latestPlayers": {},
            "eventCounts": {},
            "rejected": [],
            "invalid": [],
        }

        report = build_replay_report(Path("match.json"), summary, player_id=None)

        for heading in ("Outcome", "Hard Bugs", "Strategy Losses", "Opponent Lessons", "Recommended Cards", "Regression Checks"):
            self.assertIn(f"## {heading}", report)

    def test_stability_check(self):
        candidate = ReplayCandidate(Path("match.json"), size=10, mtime_ns=1_000_000_000)

        self.assertFalse(is_stable(candidate, stable_seconds=5, now=3))
        self.assertTrue(is_stable(candidate, stable_seconds=2, now=3))


if __name__ == "__main__":
    unittest.main()
