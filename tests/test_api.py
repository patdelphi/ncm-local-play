"""
程序说明：
- 本文件为 ncm-local-play 的后端接口单元测试。
- 通过 Flask test client + mock subprocess.run，避免测试过程中实际调用 ncm-cli/触发播放（保证幂等、安全）。
"""

import json
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch


def load_app_module():
    repo_root = Path(__file__).resolve().parents[1]
    api_path = repo_root / "ncm-api.py"
    spec = importlib.util.spec_from_file_location("ncm_api", str(api_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_app_module()
        cls.app = cls.mod.app
        cls.app.testing = True

    def setUp(self):
        self.client = self.app.test_client()
        with self.mod.session_lock:
            self.mod.session_state["active"] = False
            self.mod.session_state["playlist_id"] = None
            self.mod.session_state["entries"] = []
            self.mod.session_state["index"] = -1
            self.mod.session_state["source"] = None
        self.mod.last_played["encrypted_id"] = ""
        self.mod.last_played["original_id"] = ""

    def test_next_prev_routes_exist_and_return_json(self):
        ok_json = json.dumps({"success": True, "message": "ok"}, ensure_ascii=False)

        def fake_run(cmd, capture_output, text, encoding, errors):
            return _FakeCompletedProcess(returncode=0, stdout=ok_json, stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp_next = self.client.post("/next")
            resp_prev = self.client.post("/prev")

        self.assertEqual(resp_next.status_code, 200)
        self.assertEqual(resp_prev.status_code, 200)
        self.assertTrue(json.loads(resp_next.data.decode("utf-8"))["success"])
        self.assertTrue(json.loads(resp_prev.data.decode("utf-8"))["success"])

    def test_state_normalizes_code_200_payload_into_state(self):
        state_json = {"code": 200, "data": {"status": "playing", "title": "n - a", "position": 1, "duration": 10}}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "state" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(state_json, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.get("/state")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["state"]["status"], "playing")
        self.assertEqual(data["state"]["title"], "n - a")

    def test_play_pause_volume_return_success_when_status_ok(self):
        def fake_run(cmd, capture_output, text, encoding, errors):
            if "resume" in cmd or "pause" in cmd or "volume" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"status": "ok"}, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp_play = self.client.post("/play")
            resp_pause = self.client.post("/pause")
            resp_volume = self.client.post("/volume/30")

        self.assertEqual(resp_play.status_code, 200)
        self.assertTrue(resp_play.get_json()["success"])
        self.assertEqual(resp_pause.status_code, 200)
        self.assertTrue(resp_pause.get_json()["success"])
        self.assertEqual(resp_volume.status_code, 200)
        self.assertTrue(resp_volume.get_json()["success"])

    def test_song_play_returns_success_when_stdout_empty(self):
        def fake_run(cmd, capture_output, text, encoding, errors):
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout="", stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/song/play", json={"encrypted_id": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

    def test_song_play_returns_success_when_stdout_is_not_json(self):
        def fake_run(cmd, capture_output, text, encoding, errors):
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout="playing...", stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/song/play", json={"encrypted_id": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

    def test_session_clear_route_resets_session_state(self):
        with self.mod.session_lock:
            self.mod.session_state["active"] = True
            self.mod.session_state["playlist_id"] = "p"
            self.mod.session_state["entries"] = [{"encrypted_id": "enc1"}]
            self.mod.session_state["index"] = 0

        resp = self.client.post("/session/clear")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])

        status = self.client.get("/session/status").get_json()
        self.assertTrue(status["success"])
        self.assertFalse(status["active"])

    def test_stop_clears_session(self):
        with self.mod.session_lock:
            self.mod.session_state["active"] = True
            self.mod.session_state["playlist_id"] = "p"
            self.mod.session_state["entries"] = [{"encrypted_id": "enc1"}]
            self.mod.session_state["index"] = 0

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "stop" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"status": "ok"}, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/stop")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        status = self.client.get("/session/status").get_json()
        self.assertFalse(status["active"])

    def test_song_play_clears_session(self):
        with self.mod.session_lock:
            self.mod.session_state["active"] = True
            self.mod.session_state["playlist_id"] = "p"
            self.mod.session_state["entries"] = [{"encrypted_id": "enc1"}]
            self.mod.session_state["index"] = 0

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"status": "ok"}, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/song/play", json={"encrypted_id": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        status = self.client.get("/session/status").get_json()
        self.assertFalse(status["active"])

    def test_playlist_play_success(self):
        tracks_json = {
            "code": 200,
            "data": [
                {"id": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "originalId": 1, "name": "n1", "artists": [{"name": "a1"}]},
                {"id": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "originalId": 2, "name": "n2", "artists": [{"name": "a2"}]},
            ],
        }
        current_title = {"value": ""}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "playlist" in cmd and "tracks" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(tracks_json, ensure_ascii=False), stderr="")
            if "state" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"code": 200, "data": {"title": current_title["value"]}}, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                if "--encrypted-id" in cmd:
                    idx = cmd.index("--encrypted-id")
                    eid = cmd[idx + 1]
                    if eid == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA":
                        current_title["value"] = "n1 - a1"
                    elif eid == "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB":
                        current_title["value"] = "n2 - a2"
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True, "message": "playing"}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run), patch.object(self.mod.time, "sleep", lambda *_: None):
            resp = self.client.post(
                "/playlist/play",
                json={"original_id": "123", "encrypted_id": "456"},
            )
            resp_next = self.client.post("/session/next")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["playlist_id"], "123")
        self.assertEqual(data["mode"], "session")
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(resp_next.status_code, 200)
        self.assertTrue(resp_next.get_json()["success"])

    def test_session_play_returns_error_when_play_fails(self):
        tracks_json = {"code": 200, "data": [{"id": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "originalId": 1}, {"id": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "originalId": 2}]}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "playlist" in cmd and "tracks" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(tracks_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout="{}", stderr="play failed")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            self.client.post("/playlist/play", json={"original_id": "123", "encrypted_id": "456"})
            resp = self.client.post("/session/play", json={"index": 1})

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("播放失败", data["error"])

    def test_session_play_returns_error_when_state_does_not_change(self):
        with self.mod.session_lock:
            self.mod.session_state["active"] = True
            self.mod.session_state["playlist_id"] = "p"
            self.mod.session_state["entries"] = [{"encrypted_id": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "original_id": "1", "name": "n1", "artist": "a1"}]
            self.mod.session_state["index"] = -1

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "state" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"code": 200, "data": {"title": "old - x"}}, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"status": "ok"}, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run), patch.object(self.mod.time, "sleep", lambda *_: None):
            resp = self.client.post("/session/play", json={"index": 0})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["applied"])
        status = self.client.get("/session/status").get_json()
        self.assertEqual(status["index"], -1)

    def test_session_status_inactive_by_default(self):
        with self.mod.session_lock:
            self.mod.session_state["active"] = False
            self.mod.session_state["playlist_id"] = None
            self.mod.session_state["entries"] = []
            self.mod.session_state["index"] = -1
        resp = self.client.get("/session/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["active"])

    def test_playlist_play_success_with_only_encrypted_id(self):
        tracks_json = {"code": 200, "data": [{"id": "enc1", "originalId": 1}, {"id": "enc2", "originalId": 2}]}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "playlist" in cmd and "tracks" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(tracks_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True, "message": "playing"}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/playlist/play", json={"original_id": "", "encrypted_id": "456"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["playlist_id"], "456")
        self.assertEqual(data["mode"], "session")

    def test_extract_song_id_prefers_hex32_over_numeric_id(self):
        tracks_json = {"code": 200, "data": [{"id": 123, "encryptedId": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "originalId": 123, "name": "n1", "artists": [{"name": "a1"}]}]}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "playlist" in cmd and "tracks" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(tracks_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"status": "ok"}, ensure_ascii=False), stderr="")
            if "state" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"code": 200, "data": {"title": ""}}, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run), patch.object(self.mod.time, "sleep", lambda *_: None):
            resp = self.client.post("/playlist/play", json={"original_id": "p", "encrypted_id": "p"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["entries"][0]["encrypted_id"], "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

    def test_playlist_play_failure_returns_success_false(self):
        def fake_run(cmd, capture_output, text, encoding, errors):
            if "play" in cmd and "--playlist" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout=json.dumps({"success": False}), stderr="play fail")
            if "playlist" in cmd and "tracks" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout="{}", stderr="boom")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/playlist/play", json={"original_id": "123", "encrypted_id": "456"})

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertFalse(data["success"])
        attempts = data.get("attempts") or []
        self.assertTrue(len(attempts) > 0)
        self.assertTrue(any(a.get("returncode") == 1 for a in attempts))

    def test_queue_parses_label_to_name_and_artist(self):
        queue_json = {
            "success": True,
            "queue": [
                {"label": "歌名A - 歌手A", "current": True},
                {"label": "只有歌名", "current": False},
                {"label": "歌 - 名B - 歌手B", "current": False},
                {"label": "歌名C - 歌手C", "current": False, "encrypted_id": "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"},
            ],
            "total": 4,
        }

        def fake_run(cmd, capture_output, text, encoding, errors):
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps(queue_json, ensure_ascii=False), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.get("/queue")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["queue"][0]["name"], "歌名A")
        self.assertEqual(data["queue"][0]["artist"], "歌手A")
        self.assertEqual(data["queue"][1]["name"], "只有歌名")
        self.assertEqual(data["queue"][1]["artist"], "未知艺术家")
        self.assertEqual(data["queue"][2]["name"], "歌 - 名B")
        self.assertEqual(data["queue"][2]["artist"], "歌手B")
        self.assertEqual(data["queue"][3]["encrypted_id"], "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC")

    def test_recommend_daily_play_fails_cleanly_when_recommend_command_fails(self):
        def fake_run(cmd, capture_output, text, encoding, errors):
            if "recommend" in cmd and "daily" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout="", stderr="daily failed")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/daily/play")

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("获取每日推荐失败", data["error"])
        self.assertEqual(data["returncode"], 1)

    def test_recommend_daily_play_adds_queue_and_plays_first_song(self):
        daily_json = {"data": [{"id": "enc1", "originalId": 1}, {"id": "enc2", "originalId": 2}]}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "recommend" in cmd and "daily" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(daily_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True, "message": "playing"}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/daily/play")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "session")
        self.assertEqual(len(data["entries"]), 2)

    def test_song_resolve_returns_encrypted_id(self):
        search_json = {
            "code": 200,
            "data": {
                "records": [
                    {"id": "enc1", "name": "n", "artists": [{"name": "a"}]},
                    {"id": "enc2", "name": "x", "artists": [{"name": "y"}]},
                ]
            }
        }

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "search" in cmd and "song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(search_json, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.get("/song/resolve?name=n&artist=a")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["encrypted_id"], "enc1")

    def test_recommend_fm_play_returns_session_entries(self):
        fm_json = {"data": [{"id": "enc1", "originalId": 1}, {"id": "enc2", "originalId": 2}, {"id": "enc3", "originalId": 3}]}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "recommend" in cmd and "fm" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(fm_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/fm/play")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "session")
        self.assertEqual(len(data["entries"]), 3)

    def test_recommend_heartbeat_returns_session_entries(self):
        hb_json = {"data": [{"id": "enc1", "originalId": 1}, {"id": "enc2", "originalId": 2}]}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "recommend" in cmd and "heartbeat" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(hb_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/heartbeat", json={"song_id": "FE7C5D5FA439D80E82C92089BD10F3CF", "count": "2"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "session")
        self.assertEqual(len(data["entries"]), 2)

    def test_recommend_heartbeat_requires_numeric_song_id(self):
        hb_json = {"data": [{"id": "enc1", "originalId": 1}, {"id": "enc2", "originalId": 2}]}
        history_json = {"code": 200, "data": {"records": [{"id": "FE7C5D5FA439D80E82C92089BD10F3CF"}]}}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "user" in cmd and "history" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(history_json, ensure_ascii=False), stderr="")
            if "recommend" in cmd and "heartbeat" in cmd:
                idx = cmd.index("--songId")
                self.assertEqual(cmd[idx + 1], "FE7C5D5FA439D80E82C92089BD10F3CF")
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(hb_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with self.mod.session_lock:
            self.mod.session_state["active"] = False
            self.mod.session_state["playlist_id"] = None
            self.mod.session_state["entries"] = []
            self.mod.session_state["index"] = -1

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/heartbeat", json={"song_id": "", "count": "2"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

    def test_recommend_heartbeat_maps_hex_to_original_id(self):
        hb_json = {"data": [{"id": "enc1", "originalId": 1}, {"id": "enc2", "originalId": 2}]}
        hex_id = "FE7C5D5FA439D80E82C92089BD10F3CF"

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "recommend" in cmd and "heartbeat" in cmd:
                self.assertIn("--songId", cmd)
                idx = cmd.index("--songId")
                self.assertEqual(cmd[idx + 1], hex_id)
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(hb_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with self.mod.session_lock:
            self.mod.session_state["active"] = False
        self.mod.song_meta_cache[hex_id] = {"original_id": "123"}

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/heartbeat", json={"song_id": hex_id, "count": "2"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "session")

    def test_recommend_heartbeat_falls_back_to_queue_label(self):
        hb_json = {"data": [{"id": "enc1", "originalId": 1}]}
        queue_json = {
            "success": True,
            "queue": [{"current": True, "label": "X | 歌曲 ID: FE7C5D5FA439D80E82C92089BD10F3CF"}],
            "total": 1,
        }

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "queue" in cmd and "add" not in cmd and "clear" not in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(queue_json, ensure_ascii=False), stderr="")
            if "recommend" in cmd and "heartbeat" in cmd:
                idx = cmd.index("--songId")
                self.assertEqual(cmd[idx + 1], "FE7C5D5FA439D80E82C92089BD10F3CF")
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(hb_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with self.mod.session_lock:
            self.mod.session_state["active"] = False
            self.mod.session_state["entries"] = []
            self.mod.session_state["index"] = -1
        self.mod.last_played["original_id"] = ""
        self.mod.song_meta_cache["FE7C5D5FA439D80E82C92089BD10F3CF"] = {"original_id": "123"}

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/heartbeat", json={"song_id": "", "count": "1"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

    def test_recommend_heartbeat_retries_history_when_empty(self):
        empty_json = {"data": []}
        ok_json = {"data": [{"id": "enc1", "originalId": 1}]}
        history_json = {"code": 200, "data": {"records": [{"id": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}, {"id": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"}]}}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "recommend" in cmd and "heartbeat" in cmd:
                idx = cmd.index("--songId")
                seed = cmd[idx + 1]
                if seed == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA":
                    return _FakeCompletedProcess(returncode=0, stdout=json.dumps(empty_json, ensure_ascii=False), stderr="")
                if seed == "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB":
                    return _FakeCompletedProcess(returncode=0, stdout=json.dumps(ok_json, ensure_ascii=False), stderr="")
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(empty_json, ensure_ascii=False), stderr="")
            if "user" in cmd and "history" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(history_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with self.mod.session_lock:
            self.mod.session_state["active"] = False
            self.mod.session_state["entries"] = []
            self.mod.session_state["index"] = -1
        self.mod.last_played["encrypted_id"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/heartbeat", json={"song_id": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "count": "2"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

    def test_recommend_heartbeat_includes_debug_when_empty(self):
        hb_json = {"data": []}
        history_json = {"code": 200, "data": {"records": [{"id": "FE7C5D5FA439D80E82C92089BD10F3CF"}]}}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "recommend" in cmd and "heartbeat" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(hb_json, ensure_ascii=False), stderr="")
            if "user" in cmd and "history" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(history_json, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/heartbeat", json={"song_id": "1", "count": "2"})

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertTrue(isinstance(data.get("debug"), dict))

    def test_login_status_returns_logged_in_true(self):
        login_json = {"success": True, "data": {"isLogin": True}}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "user" in cmd and "info" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout="", stderr="user info failed")
            if "login" in cmd and "--check" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(login_json, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.get("/login/status")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["logged_in"])

    def test_login_status_returns_logged_in_true_when_code_200(self):
        login_json = {"success": True, "code": 200, "data": {}}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "user" in cmd and "info" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout="", stderr="user info failed")
            if "login" in cmd and "--check" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(login_json, ensure_ascii=False), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.get("/login/status")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["logged_in"])

    def test_login_status_uses_user_info_first(self):
        user_info_json = {"code": 200, "data": {"nickname": "u"}}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "user" in cmd and "info" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(user_info_json, ensure_ascii=False), stderr="")
            if "login" in cmd and "--check" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout="", stderr="should not call")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.get("/login/status")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["logged_in"])
        self.assertEqual(data["user"]["nickname"], "u")


if __name__ == "__main__":
    unittest.main()
