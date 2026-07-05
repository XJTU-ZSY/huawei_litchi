import asyncio
import json
import logging
import unittest
from pathlib import Path

import server


async def read_msg(reader):
    prefix = await reader.readexactly(5)
    size = int(prefix)
    return json.loads((await reader.readexactly(size)).decode("utf-8"))


async def send_msg(writer, name, data):
    writer.write(server.pack_message(name, data))
    await writer.drain()


class ProtocolTest(unittest.TestCase):
    def test_pack_message_uses_utf8_body_length(self):
        frame = server.pack_message("error", {"message": "中文", "round": 1})
        size = int(frame[:5])
        body = frame[5:]
        self.assertEqual(size, len(body))
        self.assertEqual(json.loads(body.decode("utf-8"))["msg_name"], "error")

    def test_registration_rejects_player_not_allowed_with_error(self):
        class FakeWriter:
            def __init__(self):
                self.data = bytearray()

            def write(self, data):
                self.data.extend(data)

            async def drain(self):
                pass

        class MemoryAudit:
            def __init__(self, log_dir, match_id):
                self.path = Path("memory.audit.jsonl")

            async def write(self, kind, **payload):
                pass

            def close(self):
                pass

        class MemoryReplay:
            def __init__(self, log_dir, match_id):
                self.path = Path("memory.replay.jsonl")

            async def write_message(self, msg_name, msg_data):
                pass

            def close(self):
                pass

        async def scenario():
            original_audit = server.AuditLogger
            original_replay = server.ReplayLogger
            original_setup_logging = server.setup_logging
            try:
                server.AuditLogger = MemoryAudit
                server.ReplayLogger = MemoryReplay
                server.setup_logging = lambda log_dir, verbose: logging.getLogger("test_server_null")
                match = server.MatchServer("127.0.0.1", 0, 50, 2, 1, Path("unused_logs"), False)
            finally:
                server.AuditLogger = original_audit
                server.ReplayLogger = original_replay
                server.setup_logging = original_setup_logging
            writer = FakeWriter()
            session = server.ClientSession(reader=None, writer=writer, address="fake")  # type: ignore[arg-type]
            await match.handle_registration(session, {"playerId": 9999, "playerName": "bad"})
            size = int(bytes(writer.data[:5]))
            payload = json.loads(bytes(writer.data[5:5 + size]).decode("utf-8"))
            match.close()
            return payload

        payload = asyncio.run(scenario())
        self.assertEqual(payload["msg_name"], "error")
        self.assertEqual(payload["msg_data"]["playerId"], 9999)
        self.assertEqual(payload["msg_data"]["errorCode"], "PLAYER_NOT_ALLOWED")

    def test_bad_action_round_type_returns_error_instead_of_disconnect(self):
        class FakeWriter:
            def __init__(self):
                self.data = bytearray()

            def write(self, data):
                self.data.extend(data)

            async def drain(self):
                pass

        class MemoryAudit:
            def __init__(self, log_dir, match_id):
                self.path = Path("memory.audit.jsonl")

            async def write(self, kind, **payload):
                pass

            def close(self):
                pass

        class MemoryReplay:
            def __init__(self, log_dir, match_id):
                self.path = Path("memory.replay.jsonl")

            async def write_message(self, msg_name, msg_data):
                pass

            def close(self):
                pass

        async def scenario():
            original_audit = server.AuditLogger
            original_replay = server.ReplayLogger
            original_setup_logging = server.setup_logging
            try:
                server.AuditLogger = MemoryAudit
                server.ReplayLogger = MemoryReplay
                server.setup_logging = lambda log_dir, verbose: logging.getLogger("test_server_null")
                match = server.MatchServer("127.0.0.1", 0, 50, 2, 1, Path("unused_logs"), False)
            finally:
                server.AuditLogger = original_audit
                server.ReplayLogger = original_replay
                server.setup_logging = original_setup_logging
            writer = FakeWriter()
            session = server.ClientSession(reader=None, writer=writer, address="fake", player_id=1001)  # type: ignore[arg-type]
            await match.handle_action(
                session,
                {"matchId": match.game.match_id, "round": "bad", "playerId": 1001, "actions": []},
            )
            size = int(bytes(writer.data[:5]))
            payload = json.loads(bytes(writer.data[5:5 + size]).decode("utf-8"))
            match.close()
            return payload

        payload = asyncio.run(scenario())
        self.assertEqual(payload["msg_name"], "error")
        self.assertEqual(payload["msg_data"]["round"], 0)
        self.assertEqual(payload["msg_data"]["playerId"], 1001)
        self.assertEqual(payload["msg_data"]["errorCode"], "INVALID_JSON")


class RuleTest(unittest.TestCase):
    def test_move_requires_fixed_process_after_arrival(self):
        game = server.GameState(duration_round=80, seed=1)
        p1 = game.add_player(1, "red")
        game.add_player(2, "blue")

        game.settle_round({
            1: {"actions": [{"action": "MOVE", "targetNodeId": "S02"}]},
            2: {"actions": []},
        })
        while p1.current_node_id != "S02":
            game.settle_round({1: {"actions": []}, 2: {"actions": []}})

        _, results = game.settle_round({
            1: {"actions": [{"action": "MOVE", "targetNodeId": "S03"}]},
            2: {"actions": []},
        })
        result = next(item for item in results if item["playerId"] == 1)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["errorCode"], "PROCESS_REQUIRED")

    def test_empty_action_resumes_after_active_wait_on_edge(self):
        game = server.GameState(duration_round=10, seed=1)
        p1 = game.add_player(1, "red")
        game.add_player(2, "blue")

        game.settle_round({
            1: {"actions": [{"action": "MOVE", "targetNodeId": "S02"}]},
            2: {"actions": []},
        })
        first_progress = p1.edge_progress_ms
        game.settle_round({
            1: {"actions": [{"action": "WAIT"}]},
            2: {"actions": []},
        })
        self.assertEqual(p1.state, "WAITING")
        self.assertEqual(p1.edge_progress_ms, first_progress)
        game.settle_round({1: {"actions": []}, 2: {"actions": []}})
        self.assertEqual(p1.state, "MOVING")
        self.assertGreater(p1.edge_progress_ms, first_progress)

    def test_verify_gate_before_rush_does_not_create_contest(self):
        game = server.GameState(duration_round=600, seed=1)
        p1 = game.add_player(1, "red")
        p2 = game.add_player(2, "blue")
        p1.current_node_id = "S14"
        p2.current_node_id = "S14"
        game.round = 100

        _, results = game.settle_round({
            1: {"actions": [{"action": "VERIFY_GATE", "targetNodeId": "S14"}]},
            2: {"actions": [{"action": "VERIFY_GATE", "targetNodeId": "S14"}]},
        })

        self.assertFalse(game.contests)
        self.assertEqual(p1.illegal_action_count, 1)
        self.assertEqual(p2.illegal_action_count, 1)
        self.assertEqual({item["errorCode"] for item in results}, {"VERIFY_REQUIRED"})

    def test_verify_gate_busy_rejects_late_second_processor(self):
        game = server.GameState(duration_round=600, seed=1)
        p1 = game.add_player(1, "red")
        p2 = game.add_player(2, "blue")
        p1.current_node_id = "S14"
        p2.current_node_id = "S13"
        game.round = 450

        game.settle_round({
            1: {"actions": [{"action": "VERIFY_GATE", "targetNodeId": "S14"}]},
            2: {"actions": []},
        })
        self.assertEqual(p1.state, "VERIFYING")
        p2.current_node_id = "S14"

        _, results = game.settle_round({
            1: {"actions": []},
            2: {"actions": [{"action": "VERIFY_GATE", "targetNodeId": "S14"}]},
        })

        result = next(item for item in results if item["playerId"] == 2)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["errorCode"], "OBJECT_BUSY")

    def test_gate_contest_winner_keeps_break_order_tactic(self):
        game = server.GameState(duration_round=600, seed=1)
        p1 = game.add_player(1, "red")
        p2 = game.add_player(2, "blue")
        p1.current_node_id = "S14"
        p2.current_node_id = "S14"
        game.round = 450

        game.settle_round({
            1: {"actions": [{"action": "VERIFY_GATE", "targetNodeId": "S14", "rushTactic": "BREAK_ORDER"}]},
            2: {"actions": [{"action": "VERIFY_GATE", "targetNodeId": "S14"}]},
        })
        contest_id = next(iter(game.contests))

        for _ in range(3):
            game.settle_round({
                1: {"actions": [{"action": "WINDOW_CARD", "contestId": contest_id, "card": "BING_ZHENG"}]},
                2: {"actions": []},
            })

        self.assertEqual(p1.state, "VERIFYING")
        self.assertEqual(p1.current_process.total_round, 3)
        self.assertEqual(p1.rush_tactic_used_count, 1)
        self.assertEqual(p1.good_fruit, 99)

    def test_s15_before_delivery_forbids_other_active_actions(self):
        game = server.GameState(duration_round=600, seed=1)
        p1 = game.add_player(1, "red")
        game.add_player(2, "blue")
        p1.current_node_id = "S15"
        p1.resources["ICE_BOX"] = 1

        _, results = game.settle_round({
            1: {"actions": [{"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}]},
            2: {"actions": []},
        })

        result = next(item for item in results if item["playerId"] == 1)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["errorCode"], "SAFE_ZONE_FORBIDDEN")
        self.assertEqual(p1.resources["ICE_BOX"], 1)


class EndToEndTest(unittest.TestCase):
    def test_two_clients_reach_over_and_audit_logs_messages(self):
        class MemoryAudit:
            def __init__(self, log_dir, match_id):
                self.records = []
                self.path = Path("memory.audit.jsonl")

            async def write(self, kind, **payload):
                self.records.append({"kind": kind, **payload})

            def close(self):
                pass

        class MemoryReplay:
            def __init__(self, log_dir, match_id):
                self.messages = []
                self.path = Path("memory.replay.jsonl")

            async def write_message(self, msg_name, msg_data):
                self.messages.append({"msg_name": msg_name, "msg_data": msg_data})

            def close(self):
                pass

        async def client(player_id, name, port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await send_msg(writer, "registration", {"playerId": player_id, "playerName": name, "version": "test"})
            start = await read_msg(reader)
            self.assertEqual(start["msg_name"], "start")
            match_id = start["msg_data"]["matchId"]
            await send_msg(writer, "ready", {"matchId": match_id, "round": 1, "playerId": player_id})
            seen = []
            while True:
                msg = await read_msg(reader)
                seen.append(msg["msg_name"])
                if msg["msg_name"] == "inquire":
                    round_no = msg["msg_data"]["round"]
                    await send_msg(writer, "action", {
                        "matchId": match_id,
                        "round": round_no,
                        "playerId": player_id,
                        "actions": [],
                    })
                elif msg["msg_name"] == "over":
                    break
            writer.close()
            await writer.wait_closed()
            return seen

        async def scenario():
            original_audit = server.AuditLogger
            original_replay = server.ReplayLogger
            original_setup_logging = server.setup_logging
            try:
                server.AuditLogger = MemoryAudit
                server.ReplayLogger = MemoryReplay
                server.setup_logging = lambda log_dir, verbose: logging.getLogger("test_server_null")
                match = server.MatchServer("127.0.0.1", 0, 50, 2, 1, Path("unused_logs"), False)
            finally:
                server.AuditLogger = original_audit
                server.ReplayLogger = original_replay
                server.setup_logging = original_setup_logging
            srv = await asyncio.start_server(match.handle_client, match.host, match.port)
            match.server = srv
            port = srv.sockets[0].getsockname()[1]
            game_task = asyncio.create_task(match.game_loop())
            try:
                seen = await asyncio.wait_for(asyncio.gather(
                    client(1001, "red", port),
                    client(1002, "blue", port),
                ), timeout=5)
                await game_task
                audit_kinds = {record["kind"] for record in match.audit.records}
                self.assertIn("message_in", audit_kinds)
                self.assertIn("message_out", audit_kinds)
                self.assertIn("round_settled", audit_kinds)
                self.assertEqual(match.replay.messages[0]["msg_name"], "start")
                self.assertEqual(match.replay.messages[-1]["msg_name"], "over")
                return seen
            finally:
                srv.close()
                await srv.wait_closed()
                match.close()
                await asyncio.sleep(0)

        seen = asyncio.run(scenario())
        self.assertEqual(seen[0][-1], "over")
        self.assertEqual(seen[1][-1], "over")


if __name__ == "__main__":
    unittest.main()
