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

    def test_playlist_play_success(self):
        tracks_json = {
            "code": 200,
            "data": [
                {"id": "enc1", "originalId": 1, "name": "n1", "artists": [{"name": "a1"}]},
                {"id": "enc2", "originalId": 2, "name": "n2", "artists": [{"name": "a2"}]},
            ],
        }

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "playlist" in cmd and "tracks" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(tracks_json, ensure_ascii=False), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True, "message": "playing"}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
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
        tracks_json = {"code": 200, "data": [{"id": "enc1", "originalId": 1}, {"id": "enc2", "originalId": 2}]}

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

    def test_playlist_play_failure_returns_success_false(self):
        def fake_run(cmd, capture_output, text, encoding, errors):
            if "playlist" in cmd and "tracks" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout="{}", stderr="boom")
            if "play" in cmd and "--playlist" in cmd:
                return _FakeCompletedProcess(returncode=1, stdout=json.dumps({"success": False}), stderr="play fail")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/playlist/play", json={"original_id": "123", "encrypted_id": "456"})

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertFalse(data["success"])
        attempts = data.get("attempts") or []
        self.assertTrue(len(attempts) > 0)
        self.assertTrue(any(a.get("returncode") == 1 for a in attempts))
        self.assertTrue(any("boom" in (a.get("stderr") or "") for a in attempts))

    def test_queue_parses_label_to_name_and_artist(self):
        queue_json = {
            "success": True,
            "queue": [
                {"label": "歌名A - 歌手A", "current": True},
                {"label": "只有歌名", "current": False},
                {"label": "歌 - 名B - 歌手B", "current": False},
                {"label": "歌名C - 歌手C", "current": False, "encrypted_id": "encC"},
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
        self.assertEqual(data["queue"][3]["encrypted_id"], "encC")

    def test_recommend_daily_play_fails_cleanly_when_recommend_command_fails(self):
        def fake_run(cmd, capture_output, text, encoding, errors):
            if "queue" in cmd and "clear" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
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
        daily_json = {"data": [{"id": "enc1"}, {"id": "enc2"}]}

        def fake_run(cmd, capture_output, text, encoding, errors):
            if "queue" in cmd and "clear" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
            if "recommend" in cmd and "daily" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps(daily_json, ensure_ascii=False), stderr="")
            if "queue" in cmd and "add" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")
            if "play" in cmd and "--song" in cmd:
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True, "message": "playing"}), stderr="")
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"success": True}), stderr="")

        with patch.object(self.mod.subprocess, "run", side_effect=fake_run):
            resp = self.client.post("/recommend/daily/play")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(json.loads(resp.data.decode("utf-8"))["success"])

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
