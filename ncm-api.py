#!/usr/bin/env python3
"""
ncm-cli HTTP 控制服务 - 重构版
优化播放列表管理，前端本地维护播放顺序
"""
from flask import Flask, request, jsonify, render_template
import subprocess
import sys
import os
import json
import shutil
import threading
from datetime import datetime

app = Flask(__name__, template_folder='templates')

# 全局日志存储
operation_logs = []
resolved_song_cache = {}
song_meta_cache = {}
queue_fill_state = {"task_id": None, "running": False, "total": 0, "done": 0}
queue_fill_lock = threading.Lock()
session_lock = threading.Lock()
session_state = {"active": False, "playlist_id": None, "entries": [], "index": -1}

def is_hex_32(s):
    if not s or len(s) != 32:
        return False
    for ch in s:
        if ch not in "0123456789abcdefABCDEF":
            return False
    return True

def add_log(message, log_type="status"):
    """添加操作日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    operation_logs.append({
        "timestamp": timestamp,
        "message": message,
        "type": log_type,
        "datetime": datetime.now().isoformat()
    })
    # 限制日志条数
    if len(operation_logs) > 100:
        operation_logs.pop(0)

def run_ncm(args, output_format="json"):
    """
    执行 ncm-cli 命令并返回结果
    
    Args:
        args: 命令参数列表
        output_format: 输出格式 (json|human)
    
    Returns:
        tuple: (响应数据，状态码)
    """
    try:
        # 添加输出格式参数
        if "--output" not in args:
            args.extend(["--output", output_format])

        cmd = build_ncm_command(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        if result.returncode != 0:
            return jsonify({
                "error": result.stderr,
                "returncode": result.returncode,
                "stdout": result.stdout
            }), 500

        # 返回 JSON 或纯文本结果
        if result.stdout:
            return result.stdout
        return jsonify({"status": "ok"})
    except FileNotFoundError as e:
        return jsonify({
            "error": "未找到 ncm-cli，请确认已安装并配置 PATH（或设置环境变量 NCM_CLI_PATH 指向 ncm-cli 可执行文件）",
            "detail": str(e)
        }), 500
    except OSError as e:
        if getattr(e, "winerror", None) == 193:
            return jsonify({
                "error": "ncm-cli 是 .cmd/.bat 脚本，Windows 下需要通过 cmd.exe 调用。请设置 NCM_CLI_PATH 指向 ncm-cli.cmd，或更新为已支持的调用方式。",
                "detail": str(e)
            }), 500
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_ncm_raw(args, output_format="json"):
    """
    程序说明：
    - 以“参数数组”方式执行 ncm-cli，避免 shell=True 带来的转义与注入风险。
    - 返回 (returncode, stdout, stderr) 供需要精确判断成功/失败的接口使用。
    """
    if "--output" not in args:
        args = [*args, "--output", output_format]
    try:
        result = subprocess.run(
            build_ncm_command(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        return result.returncode, (result.stdout or ""), (result.stderr or "")
    except FileNotFoundError as e:
        return 127, "", str(e)
    except OSError as e:
        return 126, "", str(e)

def build_ncm_command(args):
    """
    程序说明：
    - 生成可在当前系统正确执行的 ncm-cli 命令数组。
    - Windows 下 npm 安装的 ncm-cli 通常是 ncm-cli.cmd，需要用 cmd.exe /c 调用。
    - 支持环境变量 NCM_CLI_PATH，优先级最高。
    """
    configured = os.environ.get("NCM_CLI_PATH", "").strip()
    if configured:
        resolved = configured
    else:
        resolved = shutil.which("ncm-cli") or ""
        if not resolved and os.name == "nt":
            appdata = os.environ.get("APPDATA", "")
            candidate = os.path.join(appdata, "npm", "ncm-cli.cmd") if appdata else ""
            if candidate and os.path.exists(candidate):
                resolved = candidate
        if not resolved:
            resolved = "ncm-cli"

    resolved_lower = str(resolved).lower()
    if os.name == "nt" and (resolved_lower.endswith(".cmd") or resolved_lower.endswith(".bat")):
        return ["cmd.exe", "/d", "/s", "/c", resolved, *args]
    return [resolved, *args]

def normalize_text(s):
    if s is None:
        return ""
    return str(s).strip().lower()

def resolve_song_ids(name, artist):
    cache_key = f"{normalize_text(name)}|{normalize_text(artist)}"
    cached = resolved_song_cache.get(cache_key)
    if isinstance(cached, dict) and cached.get("encrypted_id"):
        return cached

    keyword = f"{name} {artist}".strip()
    returncode, stdout, stderr = run_ncm_raw(["search", "song", "--keyword", keyword], "json")
    if returncode != 0:
        return None

    try:
        data = json.loads(stdout)
    except Exception:
        return None

    if data.get("code") != 200:
        return None

    records = (data.get("data") or {}).get("records") or []
    if not records:
        return None

    target_name = normalize_text(name)
    target_artist = normalize_text(artist)

    def score_song(s):
        s_name = normalize_text(s.get("name"))
        artists = s.get("artists") or []
        artist_str = normalize_text(" ".join([a.get("name", "") for a in artists]))
        score = 0
        if s_name == target_name:
            score += 10
        if target_artist and target_artist in artist_str:
            score += 5
        if artist_str and artist_str in target_artist:
            score += 2
        return score

    best = max(records, key=score_song)
    encrypted_id = best.get("id")
    original_id = best.get("originalId") or best.get("original_id") or ""
    if encrypted_id:
        resolved = {"encrypted_id": str(encrypted_id), "original_id": str(original_id) if original_id else ""}
        resolved_song_cache[cache_key] = resolved
        return resolved
    return None

def extract_records(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("records", "songs", "tracks", "list", "items"):
            v = data.get(k)
            if isinstance(v, list):
                return v
        playlist = data.get("playlist")
        if isinstance(playlist, dict):
            for k in ("tracks", "songs", "records", "items"):
                v = playlist.get(k)
                if isinstance(v, list):
                    return v
    if isinstance(payload.get("records"), list):
        return payload.get("records")
    return []

def extract_song_id(item):
    if not isinstance(item, dict):
        return ""
    for k in ("encrypted_id", "encryptedId", "encryptId", "id", "songId"):
        v = item.get(k)
        if v:
            return str(v)
    nested = item.get("song")
    if isinstance(nested, dict):
        for k in ("id", "encryptedId", "songId"):
            v = nested.get(k)
            if v:
                return str(v)
    return ""

def extract_song_original_id(item):
    if not isinstance(item, dict):
        return ""
    for k in ("original_id", "originalId", "originId", "songOriginalId"):
        v = item.get(k)
        if v:
            return str(v)
    nested = item.get("song")
    if isinstance(nested, dict):
        for k in ("originalId", "original_id", "originId"):
            v = nested.get(k)
            if v:
                return str(v)
    return ""

def extract_song_entries_from_payload(payload):
    records = extract_records(payload)
    entries = []
    for r in records:
        encrypted_id = extract_song_id(r)
        if not encrypted_id:
            continue
        original_id = extract_song_original_id(r)
        name = ""
        artist = ""
        if isinstance(r, dict):
            name = r.get("name") or ""
            artists = r.get("artists")
            if isinstance(artists, list):
                artist = ",".join([a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")])
            nested = r.get("song")
            if not name and isinstance(nested, dict):
                name = nested.get("name") or ""
            if not artist and isinstance(nested, dict):
                artists = nested.get("artists")
                if isinstance(artists, list):
                    artist = ",".join([a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")])

        entry = {"encrypted_id": encrypted_id, "original_id": original_id, "name": name, "artist": artist}
        entries.append(entry)
        if encrypted_id and (name or artist):
            song_meta_cache[str(encrypted_id)] = {"name": name, "artist": artist, "original_id": original_id}
    return entries

def try_ncm_json(args):
    returncode, stdout, stderr = run_ncm_raw(args, "json")
    if returncode != 0:
        return None, {
            "returncode": returncode,
            "stderr": stderr,
            "stdout": stdout,
            "args": args,
        }
    try:
        return json.loads(stdout), None
    except Exception:
        return None, {
            "returncode": returncode,
            "stderr": stderr,
            "stdout": stdout,
            "args": args,
            "error": "JSON解析失败",
        }

def play_song_checked(encrypted_id, original_id=""):
    args = ["play", "--song", "--encrypted-id", str(encrypted_id)]
    if original_id:
        args.extend(["--original-id", str(original_id)])
    data, err = try_ncm_json(args)
    if err:
        return False, {"error": "播放失败", **err}
    if isinstance(data, dict) and (data.get("success") is True or data.get("status") == "ok"):
        return True, data
    return False, {"error": "播放失败", "raw": data, "args": args}

def load_playlist_song_ids(original_id, encrypted_id=None):
    """
    程序说明：
    - 尽最大可能从 ncm-cli 拿到歌单歌曲的 encrypted_id 列表。
    - 不同版本/接口可能对 original_id/encrypted_id 参数含义不一致，因此这里做多种兜底尝试。
    """
    attempts = []

    def handle_success(data):
        if not isinstance(data, dict):
            return None
        if data.get("code") != 200:
            return None
        entries = extract_song_entries_from_payload(data)
        if not entries:
            return None
        return entries

    candidates = []
    if encrypted_id:
        candidates.append(["playlist", "tracks", "--playlistId", str(encrypted_id), "--limit", "500", "--offset", "0"])
        candidates.append(["playlist", "get", "--playlistId", str(encrypted_id)])
    if encrypted_id:
        candidates.append(["playlist", "tracks", "--playlistId", str(encrypted_id)])
    if original_id:
        candidates.append(["playlist", "tracks", "--playlistId", str(original_id), "--limit", "500", "--offset", "0"])
        candidates.append(["playlist", "get", "--playlistId", str(original_id)])

    for args in candidates:
        data, err = try_ncm_json(args)
        if err:
            attempts.append(err)
            continue
        entries = handle_success(data)
        if entries:
            return entries, None
        attempts.append({"args": args, "error": "返回code非200或无法提取歌曲ID", "raw": data})

    return None, {"error": "获取歌单歌曲失败", "attempts": attempts}

def queueize_and_play(song_entries):
    task_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    with queue_fill_lock:
        queue_fill_state["task_id"] = task_id
        queue_fill_state["running"] = True
        queue_fill_state["total"] = len(song_entries)
        queue_fill_state["done"] = 0

    run_ncm_raw(["queue", "clear"], "human")

    def add_entry(e):
        encrypted_id = e.get("encrypted_id")
        if not encrypted_id:
            return
        original_id = e.get("original_id") or ""
        args = ["queue", "add", "--encrypted-id", str(encrypted_id)]
        if original_id:
            args.extend(["--original-id", str(original_id)])
        run_ncm_raw(args, "human")
        with queue_fill_lock:
            if queue_fill_state.get("task_id") == task_id and queue_fill_state.get("running"):
                queue_fill_state["done"] = min(queue_fill_state.get("done", 0) + 1, queue_fill_state.get("total", 0))

    first = next((e for e in song_entries if e.get("encrypted_id")), None)
    if not first:
        return jsonify({"success": False, "error": "队列为空"}), 500

    sync_limit = 30
    for e in song_entries[:sync_limit]:
        add_entry(e)

    if len(song_entries) > sync_limit:
        rest = list(song_entries[sync_limit:])

        def background_add():
            for e in rest:
                add_entry(e)
            with queue_fill_lock:
                if queue_fill_state.get("task_id") == task_id:
                    queue_fill_state["running"] = False

        threading.Thread(target=background_add, daemon=True).start()
    else:
        with queue_fill_lock:
            if queue_fill_state.get("task_id") == task_id:
                queue_fill_state["running"] = False

    play_args = ["play", "--song", "--encrypted-id", str(first.get("encrypted_id"))]
    if first.get("original_id"):
        play_args.extend(["--original-id", str(first.get("original_id"))])
    return run_ncm(play_args)

def session_set_playlist(playlist_id, entries, start_index=0):
    with session_lock:
        session_state["active"] = True
        session_state["playlist_id"] = str(playlist_id) if playlist_id else None
        session_state["entries"] = entries or []
        session_state["index"] = int(start_index) if entries else -1

def session_get_snapshot():
    with session_lock:
        return {
            "active": bool(session_state.get("active")),
            "playlist_id": session_state.get("playlist_id"),
            "index": int(session_state.get("index", -1)),
            "total": len(session_state.get("entries") or []),
            "entries": list(session_state.get("entries") or []),
        }

def session_play_index(index):
    snap = session_get_snapshot()
    if not snap["active"]:
        return jsonify({"success": False, "error": "session 未激活"}), 400
    if index < 0 or index >= snap["total"]:
        return jsonify({"success": False, "error": "index 越界"}), 400

    entry = snap["entries"][index]
    encrypted_id = entry.get("encrypted_id")
    original_id = entry.get("original_id") or ""
    if not encrypted_id:
        return jsonify({"success": False, "error": "缺少 encrypted_id"}), 500

    ok, payload = play_song_checked(encrypted_id, original_id)
    if not ok:
        return jsonify({"success": False, **payload}), 500

    with session_lock:
        session_state["index"] = int(index)

    return jsonify({
        "success": True,
        "playlist_id": snap["playlist_id"],
        "index": int(index),
        "song": {
            "name": entry.get("name", ""),
            "artist": entry.get("artist", ""),
            "encrypted_id": encrypted_id,
            "original_id": original_id,
        },
        "ncm": payload,
    })

@app.route("/session/status", methods=["GET"])
def session_status():
    snap = session_get_snapshot()
    return jsonify({"success": True, **{k: snap[k] for k in ("active", "playlist_id", "index", "total")}})

@app.route("/session/playlist", methods=["GET"])
def session_playlist():
    snap = session_get_snapshot()
    return jsonify({
        "success": True,
        "active": snap["active"],
        "playlist_id": snap["playlist_id"],
        "index": snap["index"],
        "total": snap["total"],
        "entries": snap["entries"],
    })

@app.route("/session/play", methods=["POST"])
def session_play():
    data = request.json or {}
    index = data.get("index", None)
    if index is None:
        return jsonify({"success": False, "error": "需要提供 index"}), 400
    try:
        index = int(index)
    except Exception:
        return jsonify({"success": False, "error": "index 必须为整数"}), 400
    return session_play_index(index)

@app.route("/session/next", methods=["POST"])
def session_next():
    snap = session_get_snapshot()
    if not snap["active"]:
        return jsonify({"success": False, "error": "session 未激活"}), 400
    next_index = min(snap["index"] + 1, snap["total"] - 1) if snap["total"] > 0 else -1
    return session_play_index(next_index)

@app.route("/session/prev", methods=["POST"])
def session_prev():
    snap = session_get_snapshot()
    if not snap["active"]:
        return jsonify({"success": False, "error": "session 未激活"}), 400
    prev_index = max(snap["index"] - 1, 0) if snap["total"] > 0 else -1
    return session_play_index(prev_index)

@app.route("/queue/fill/status", methods=["GET"])
def queue_fill_status():
    with queue_fill_lock:
        return jsonify({"success": True, **queue_fill_state})

def try_play_playlist(original_id=None, encrypted_id=None):
    attempts = []
    candidates = []
    if encrypted_id and original_id:
        candidates.append(["play", "--playlist", "--encrypted-id", str(encrypted_id), "--original-id", str(original_id)])
    if encrypted_id:
        candidates.append(["play", "--playlist", "--encrypted-id", str(encrypted_id)])
    if original_id:
        candidates.append(["play", "--playlist", "--original-id", str(original_id)])
    if encrypted_id and original_id:
        candidates.append(["play", "--playlist", "--encrypted-id", str(original_id), "--original-id", str(encrypted_id)])

    for args in candidates:
        data, err = try_ncm_json(args)
        if err:
            attempts.append(err)
            continue
        if isinstance(data, dict) and (data.get("success") is True or data.get("code") == 200):
            return True, {"attempts": attempts, "raw": data}
        attempts.append({"args": args, "raw": data, "error": "播放歌单返回非成功"})

    return False, {"attempts": attempts}

# ============ 基础路由 ============

@app.route("/")
def index():
    """服务状态页面 - 前端控制界面"""
    return render_template("index.html")

@app.route("/api/info")
def api_info():
    """API 信息接口"""
    return jsonify({
        "status": "ok",
        "service": "ncm-cli HTTP 控制服务",
        "version": "2.0",
        "endpoints": {
            "播放控制": ["/state", "/play", "/pause", "/stop", "/next", "/prev", "/volume/<level>"],
            "歌单管理": ["/playlist/collected", "/playlist/radar", "/playlist/play"],
            "用户信息": ["/user/info", "/user/favorite"],
            "推荐": ["/recommend/daily", "/recommend/fm"],
            "搜索": ["/search?keyword=xxx"],
            "登录": ["/login/status"]
        }
    })

@app.route("/api/logs")
def get_logs():
    """获取操作日志"""
    return jsonify({"logs": operation_logs[-50:]})


# ============ 播放控制 ============

@app.route("/state", methods=["GET"])
def state():
    """获取当前播放状态"""
    return run_ncm(["state"])

@app.route("/play", methods=["POST"])
def play():
    """播放（恢复播放）"""
    add_log("执行命令：play", "command")
    result = run_ncm(["resume"])
    add_log("播放控制：已恢复播放", "status")
    return result

@app.route("/pause", methods=["POST"])
def pause():
    """暂停播放"""
    add_log("执行命令：pause", "command")
    result = run_ncm(["pause"])
    add_log("播放控制：已暂停", "status")
    return result

@app.route("/stop", methods=["POST"])
def stop():
    """停止播放"""
    add_log("执行命令：stop", "command")
    result = run_ncm(["stop"])
    add_log("播放控制：已停止", "status")
    return result

@app.route("/next", methods=["POST"])
def next_song():
    """下一首"""
    snap = session_get_snapshot()
    if snap["active"]:
        add_log("执行命令：session next", "command")
        return session_next()
    add_log("执行命令：next", "command")
    result = run_ncm(["next"])
    add_log("播放控制：下一首", "status")
    return result

@app.route("/prev", methods=["POST"])
def prev_song():
    """上一首"""
    snap = session_get_snapshot()
    if snap["active"]:
        add_log("执行命令：session prev", "command")
        return session_prev()
    add_log("执行命令：prev", "command")
    result = run_ncm(["prev"])
    add_log("播放控制：上一首", "status")
    return result

@app.route("/seek/<int:seconds>", methods=["POST"])
def seek(seconds):
    """跳转到指定时间（秒）"""
    add_log(f"跳转到 {seconds}秒", "command")
    result = run_ncm(["seek", str(seconds)])
    add_log(f"已跳转到 {seconds}秒", "status")
    return result


@app.route("/song/like", methods=["POST"])
def song_like():
    """红心歌曲"""
    data = request.json or {}
    encrypted_id = data.get("encrypted_id", "")
    
    if not encrypted_id:
        return jsonify({"error": "需要提供 encrypted_id"}), 400
    
    add_log(f"红心歌曲：{encrypted_id[:8]}...", "command")
    result = run_ncm(["song", "like", "--encrypted-id", encrypted_id])
    add_log("已添加到红心", "status")
    return result


@app.route("/song/dislike", methods=["POST"])
def song_dislike():
    """取消红心歌曲"""
    data = request.json or {}
    encrypted_id = data.get("encrypted_id", "")
    
    if not encrypted_id:
        return jsonify({"error": "需要提供 encrypted_id"}), 400
    
    add_log(f"取消红心：{encrypted_id[:8]}...", "command")
    result = run_ncm(["song", "dislike", "--encrypted-id", encrypted_id])
    add_log("已取消红心", "status")
    return result


@app.route("/song/lyric", methods=["GET"])
def song_lyric():
    """获取歌曲歌词"""
    encrypted_id = request.args.get("encrypted_id", "")
    
    if not encrypted_id:
        return jsonify({"error": "需要提供 encrypted_id"}), 400
    
    return run_ncm(["song", "lyric", "--encrypted-id", encrypted_id])


@app.route("/user/history", methods=["GET"])
def user_history():
    """获取最近播放歌曲"""
    return run_ncm(["user", "history"])


@app.route("/user/listen-ranking", methods=["GET"])
def user_listen_ranking():
    """获取听歌排行"""
    return run_ncm(["user", "listen-ranking"])


@app.route("/playlist/created", methods=["GET"])
def playlist_created():
    """获取我创建的歌单"""
    return run_ncm(["playlist", "created"])


@app.route("/playlist/tracks", methods=["GET"])
def playlist_tracks():
    """获取歌单歌曲列表"""
    original_id = request.args.get("original_id", "")
    if not original_id:
        return jsonify({"error": "需要提供 original_id"}), 400
    return run_ncm(["playlist", "tracks", "--original-id", original_id])


@app.route("/album/get", methods=["GET"])
def album_get():
    """获取专辑详情"""
    original_id = request.args.get("original_id", "")
    if not original_id:
        return jsonify({"error": "需要提供 original_id"}), 400
    return run_ncm(["album", "get", "--original-id", original_id])


@app.route("/album/tracks", methods=["GET"])
def album_tracks():
    """获取专辑歌曲列表"""
    original_id = request.args.get("original_id", "")
    if not original_id:
        return jsonify({"error": "需要提供 original_id"}), 400
    return run_ncm(["album", "tracks", "--original-id", original_id])


@app.route("/volume/<int:level>", methods=["POST"])
def volume(level):
    """设置音量 (0-100)"""
    level = max(0, min(100, level))
    add_log(f"执行命令：volume {level}", "command")
    result = run_ncm(["volume", str(level)])
    add_log(f"音量控制：已设置为 {level}%", "status")
    return result


# ============ 歌曲播放 ============

@app.route("/song/play", methods=["POST"])
def song_play():
    """
    播放单曲
    需要提供歌曲的 encrypted_id（original_id 可选）
    """
    data = request.json or {}
    original_id = data.get("original_id", "")
    encrypted_id = data.get("encrypted_id", "")
    index = data.get("index", -1)  # 前端传入的索引

    if not encrypted_id:
        return jsonify({"error": "需要提供 encrypted_id"}), 400

    add_log(f"播放单曲：{encrypted_id[:8]}... (索引:{index})", "command")
    
    args = ["play", "--song", "--encrypted-id", encrypted_id]
    if original_id:
        args.extend(["--original-id", str(original_id)])
    result = run_ncm(args)
    
    add_log("单曲播放：已发送播放请求", "status")
    return result

@app.route("/song/resolve", methods=["GET"])
def song_resolve():
    name = request.args.get("name", "")
    artist = request.args.get("artist", "")
    if not name:
        return jsonify({"success": False, "error": "需要提供 name"}), 400

    resolved = resolve_song_ids(name, artist)
    if not resolved:
        return jsonify({"success": False, "error": "未找到歌曲"}), 404

    return jsonify({"success": True, **resolved})


# ============ 推荐播放 ============

@app.route("/recommend/daily/play", methods=["POST"])
def play_recommend_daily():
    """
    播放每日推荐
    先清空队列，然后获取每日推荐并逐首添加到队列
    """
    add_log("播放每日推荐", "command")
    
    # 先清空队列
    run_ncm(["queue", "clear"])
    
    # 获取每日推荐
    try:
        returncode, stdout, stderr = run_ncm_raw(["recommend", "daily", "--limit", "30"], "json")
        if returncode != 0:
            add_log(f"获取每日推荐失败：{stderr.strip()}", "error")
            return jsonify({"error": "获取每日推荐失败", "stderr": stderr, "stdout": stdout, "returncode": returncode}), 500

        data = json.loads(stdout)
        songs = data.get('data', [])
        
        if not songs or len(songs) == 0:
            add_log("每日推荐为空", "error")
            return jsonify({"error": "每日推荐为空"}), 400
        
        # 逐首添加到队列
        for song in songs:
            args = ["queue", "add", "--encrypted-id", str(song.get("id"))]
            if song.get("originalId"):
                args.extend(["--original-id", str(song.get("originalId"))])
            run_ncm(args, "json")
        
        # 播放第一首
        if songs:
            first_song = songs[0]
            play_args = ["play", "--song", "--encrypted-id", str(first_song.get("id"))]
            if first_song.get("originalId"):
                play_args.extend(["--original-id", str(first_song.get("originalId"))])
            result = run_ncm(play_args)
            add_log(f"每日推荐：已加载 {len(songs)} 首歌曲", "status")
            return result
        
        return jsonify({"status": "ok"})
    except Exception as e:
        add_log(f"播放每日推荐失败：{str(e)}", "error")
        return jsonify({"error": str(e)}), 500


@app.route("/recommend/fm/play", methods=["POST"])
def play_fm():
    """
    播放私人 FM
    """
    add_log("播放私人 FM", "command")
    
    # 获取 FM 歌曲
    try:
        returncode, stdout, stderr = run_ncm_raw(["recommend", "fm", "--limit", "3"], "json")
        if returncode != 0:
            add_log(f"获取 FM 失败：{stderr.strip()}", "error")
            return jsonify({"error": "获取 FM 失败", "stderr": stderr, "stdout": stdout, "returncode": returncode}), 500

        data = json.loads(stdout)
        songs = data.get('data', [])
        
        if not songs or len(songs) == 0:
            return jsonify({"error": "FM 推荐为空"}), 400
        
        # 清空队列并添加 FM 歌曲
        run_ncm(["queue", "clear"])
        
        for song in songs:
            args = ["queue", "add", "--encrypted-id", str(song.get("id"))]
            if song.get("originalId"):
                args.extend(["--original-id", str(song.get("originalId"))])
            run_ncm(args, "json")
        
        # 播放第一首
        first_song = songs[0]
        play_args = ["play", "--song", "--encrypted-id", str(first_song.get("id"))]
        if first_song.get("originalId"):
            play_args.extend(["--original-id", str(first_song.get("originalId"))])
        result = run_ncm(play_args)
        
        add_log(f"私人 FM：已加载 {len(songs)} 首歌曲", "status")
        return result
    except Exception as e:
        add_log(f"播放 FM 失败：{str(e)}", "error")
        return jsonify({"error": str(e)}), 500


@app.route("/recommend/heartbeat", methods=["POST"])
def play_heartbeat():
    """
    播放心动模式推荐
    """
    data = request.json or {}
    song_id = data.get("song_id", "")
    count = data.get("count", "20")
    
    add_log(f"播放心动模式 (song_id={song_id[:8] if song_id else ''}...)", "command")
    
    # 获取心动模式推荐
    try:
        cmd = [
            "recommend", "heartbeat",
            "--songId", song_id if song_id else "",
            "--count", count
        ]
        returncode, stdout, stderr = run_ncm_raw(cmd, "json")
        if returncode != 0:
            add_log(f"获取心动模式失败：{stderr.strip()}", "error")
            return jsonify({"error": "获取心动模式失败", "stderr": stderr, "stdout": stdout, "returncode": returncode}), 500

        result_data = json.loads(stdout)
        songs = result_data.get('data', [])
        
        if not songs or len(songs) == 0:
            return jsonify({"error": "心动模式推荐为空"}), 400
        
        # 清空队列并添加推荐歌曲
        run_ncm(["queue", "clear"])
        
        for song in songs:
            args = ["queue", "add", "--encrypted-id", str(song.get("id"))]
            if song.get("originalId"):
                args.extend(["--original-id", str(song.get("originalId"))])
            run_ncm(args, "json")
        
        # 播放第一首
        first_song = songs[0]
        play_args = ["play", "--song", "--encrypted-id", str(first_song.get("id"))]
        if first_song.get("originalId"):
            play_args.extend(["--original-id", str(first_song.get("originalId"))])
        result = run_ncm(play_args)
        
        add_log(f"心动模式：已加载 {len(songs)} 首歌曲", "status")
        return result
    except Exception as e:
        add_log(f"播放心动模式失败：{str(e)}", "error")
        return jsonify({"error": str(e)}), 500


# ============ 用户 ============

@app.route("/user/info", methods=["GET"])
def user_info():
    """获取用户信息"""
    return run_ncm(["user", "info"])

@app.route("/user/favorite", methods=["GET"])
def user_favorite():
    """获取用户收藏"""
    return run_ncm(["user", "favorite"])

@app.route("/user/favorite/play", methods=["POST"])
def play_user_favorite():
    """播放用户红心歌单"""
    add_log("播放红心歌单", "command")
    # 先获取红心歌单信息
    try:
        returncode, stdout, stderr = run_ncm_raw(["user", "favorite"], "json")
        if returncode != 0:
            add_log(f"获取红心歌单信息失败：{stderr.strip()}", "error")
            return jsonify({"error": "获取红心歌单信息失败", "stderr": stderr, "stdout": stdout, "returncode": returncode}), 500

        data = json.loads(stdout)
        original_id = data.get('data', {}).get('originalId', '')
        encrypted_id = data.get('data', {}).get('id', '')
        
        if not original_id or not encrypted_id:
            add_log("获取红心歌单 ID 失败", "error")
            return jsonify({"error": "获取红心歌单 ID 失败"}), 500

        song_entries, err = load_playlist_song_ids(original_id, encrypted_id)
        if err:
            ok, detail = try_play_playlist(original_id=original_id, encrypted_id=encrypted_id)
            if ok:
                add_log("红心歌单：无法获取曲目列表，已切换为歌单模式播放", "status")
                return jsonify({
                    "success": True,
                    "status": "ok",
                    "mode": "playlist",
                    "playlist_id": str(original_id) if original_id else str(encrypted_id),
                    "warning": "无法获取歌单曲目列表，已使用 ncm-cli 歌单模式播放；队列展示可能为空",
                    "attempts": err.get("attempts", []),
                    "play_attempts": detail.get("attempts", []),
                })

            add_log(f"红心歌单加载失败：{err.get('error')}", "error")
            return jsonify({"success": False, **err}), 500

        session_set_playlist(encrypted_id or original_id, song_entries, 0)
        first = song_entries[0] if song_entries else None
        if not first:
            return jsonify({"success": False, "error": "歌单为空"}), 500
        ok, payload = play_song_checked(first.get("encrypted_id"), first.get("original_id") or "")
        if not ok:
            return jsonify({"success": False, **payload}), 500
        add_log(f"红心歌单：已加载 {len(song_entries)} 首", "status")
        return jsonify({
            "success": True,
            "status": "ok",
            "mode": "session",
            "playlist_id": str(encrypted_id or original_id),
            "song_count": len(song_entries),
            "index": 0,
            "entries": song_entries,
        })
    except Exception as e:
        add_log(f"播放红心歌单失败：{str(e)}", "error")
        return jsonify({"error": str(e)}), 500


# ============ 歌单管理 ============

@app.route("/playlist/collected", methods=["GET"])
def playlist_collected():
    """获取我收藏的歌单列表"""
    return run_ncm(["playlist", "collected"])

@app.route("/playlist/radar", methods=["GET"])
def playlist_radar():
    """获取雷达歌单"""
    return run_ncm(["playlist", "radar"])

@app.route("/playlist/play", methods=["POST"])
def playlist_play():
    """
    播放歌单
    需要提供歌单的 original_id 或 encrypted_id
    """
    data = request.json or {}
    original_id = data.get("original_id", "")
    encrypted_id = data.get("encrypted_id", "")

    if not original_id and not encrypted_id:
        return jsonify({"error": "需要提供 original_id 或 encrypted_id", "success": False}), 400

    playlist_id_for_log = original_id or encrypted_id
    add_log(f"播放歌单：ID={playlist_id_for_log}", "command")

    try:
        song_entries, err = load_playlist_song_ids(original_id, encrypted_id)
        if err:
            ok, detail = try_play_playlist(original_id=original_id, encrypted_id=encrypted_id)
            if ok:
                add_log("歌单播放：无法获取曲目列表，已切换为歌单模式播放", "status")
                return jsonify({
                    "success": True,
                    "status": "ok",
                    "mode": "playlist",
                    "playlist_id": playlist_id_for_log,
                    "warning": "无法获取歌单曲目列表，已使用 ncm-cli 歌单模式播放；队列展示可能为空",
                    "attempts": err.get("attempts", []),
                    "play_attempts": detail.get("attempts", []),
                })

            add_log(f"歌单加载失败：{err.get('error')}", "error")
            return jsonify({"success": False, "playlist_id": playlist_id_for_log, **err}), 500

        session_set_playlist(encrypted_id or original_id, song_entries, 0)
        first = song_entries[0] if song_entries else None
        if not first:
            return jsonify({"success": False, "error": "歌单为空"}), 500
        ok, payload = play_song_checked(first.get("encrypted_id"), first.get("original_id") or "")
        if not ok:
            return jsonify({"success": False, **payload}), 500
        add_log(f"歌单播放：已加载 {len(song_entries)} 首", "status")
        return jsonify({
            "success": True,
            "status": "ok",
            "mode": "session",
            "playlist_id": playlist_id_for_log,
            "song_count": len(song_entries),
            "index": 0,
            "entries": song_entries,
        })
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ============ 搜索 ============

@app.route("/search", methods=["GET"])
def search():
    """
    综合搜索
    参数：keyword - 搜索关键词
    """
    keyword = request.args.get("keyword", "")
    if not keyword:
        return jsonify({"error": "需要提供 keyword 参数"}), 400
    add_log(f"搜索：{keyword}", "command")
    return run_ncm(["search", "all", "--keyword", keyword])

@app.route("/search/song", methods=["GET"])
def search_song():
    """
    搜索歌曲
    参数：keyword - 搜索关键词
    """
    keyword = request.args.get("keyword", "")
    if not keyword:
        return jsonify({"error": "需要提供 keyword 参数"}), 400
    
    add_log(f"搜索歌曲：{keyword}", "command")

    result = subprocess.run(
        ["ncm-cli", "search", "song", "--keyword", keyword, "--output", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    
    try:
        data = json.loads(result.stdout)
        # 转换数据格式
        if data.get('code') == 200:
            data['data']['songs'] = data['data'].get('records', [])
        return jsonify(data)
    except:
        return jsonify({"error": result.stderr}), 500

@app.route("/search/playlist", methods=["GET"])
def search_playlist():
    """
    搜索歌单
    参数：keyword - 搜索关键词
    """
    keyword = request.args.get("keyword", "")
    if not keyword:
        return jsonify({"error": "需要提供 keyword 参数"}), 400
    add_log(f"搜索歌单：{keyword}", "command")
    return run_ncm(["search", "playlist", "--keyword", keyword])


# ============ 登录 ============

@app.route("/login/status", methods=["GET"])
def login_status():
    """检查登录状态"""
    """
    程序说明：
    - Windows/CLI 场景下，“是否登录”最可靠的判断是能否成功获取用户信息：
      ncm-cli user info
    - 因此此接口优先调用 user info 判定登录；必要时再 fallback 到 login --check。
    """
    returncode, stdout, stderr = run_ncm_raw(["user", "info"], "json")
    if returncode == 0:
        try:
            data = json.loads(stdout)
        except Exception:
            return jsonify({
                "success": False,
                "error": "用户信息解析失败",
                "stdout": stdout,
                "stderr": stderr,
            }), 500

        logged_in = bool(data.get("code") == 200 and data.get("data"))
        return jsonify({
            "success": True,
            "logged_in": logged_in,
            "user": data.get("data") if logged_in else None,
            "raw": data,
        })

    fallback_code, fallback_stdout, fallback_stderr = run_ncm_raw(["login", "--check"], "json")
    if fallback_code != 0:
        return jsonify({
            "success": False,
            "error": "检查登录状态失败",
            "returncode": returncode,
            "stderr": stderr,
            "stdout": stdout,
            "fallback_returncode": fallback_code,
            "fallback_stderr": fallback_stderr,
            "fallback_stdout": fallback_stdout,
        }), 500

    try:
        fallback_data = json.loads(fallback_stdout)
    except Exception:
        return jsonify({
            "success": False,
            "error": "登录状态解析失败",
            "stdout": fallback_stdout,
            "stderr": fallback_stderr,
        }), 500

    logged_in = bool(fallback_data.get("success") is True and (fallback_data.get("code") == 200 or fallback_data.get("data")))
    fallback_data["logged_in"] = logged_in
    return jsonify(fallback_data)

@app.route("/login", methods=["POST"])
def login():
    """执行登录"""
    return run_ncm(["login"])


# ============ 队列管理 ============

@app.route("/queue", methods=["GET"])
def queue_list():
    """获取播放队列"""
    add_log("获取播放队列", "command")
    try:
        returncode, stdout, stderr = run_ncm_raw(["queue"], "json")
        if returncode != 0:
            return jsonify({"error": stderr, "success": False, "returncode": returncode, "stdout": stdout}), 500

        data = json.loads(stdout)
        if not data.get('success'):
            return jsonify(data)

        hydrate = request.args.get("hydrate", "0") == "1"

        # 解析队列数据，为每首歌添加 name 和 artist 字段
        queue = data.get('queue', [])
        for song in queue:
            # 从 label 解析歌曲名和歌手 (格式：歌曲名 - 歌手)
            label = song.get('label', '')
            parts = label.rsplit(' - ', 1)
            if len(parts) == 2:
                song['name'] = parts[0].strip()
                song['artist'] = parts[1].strip()
            else:
                song['name'] = label
                song['artist'] = '未知艺术家'
            # 兼容：不要覆盖 ncm-cli 已返回的 ID；若没有则尝试从其它字段归一化
            if not song.get('encrypted_id'):
                song['encrypted_id'] = (
                    song.get('encryptedId')
                    or song.get('encryptId')
                    or song.get('id')
                    or song.get('songId')
                    or ''
                )
            if not song.get('original_id'):
                song['original_id'] = (
                    song.get('originalId')
                    or song.get('originId')
                    or ''
                )
            meta_key = song.get('encrypted_id') or (song.get('name') if is_hex_32(song.get('name')) else "")
            meta = song_meta_cache.get(str(meta_key)) if meta_key else None
            if meta and (song.get('artist') == '未知艺术家' or is_hex_32(song.get('name')) or not song.get('name')):
                if meta.get("name"):
                    song['name'] = meta.get("name")
                if meta.get("artist"):
                    song['artist'] = meta.get("artist")
                if meta.get("original_id") and not song.get('original_id'):
                    song['original_id'] = meta.get("original_id")
            if is_hex_32(song.get('name')) and song.get('artist') == '未知艺术家':
                song['name'] = '未知歌曲'
            if not song.get('encrypted_id') and hydrate and song.get('name'):
                resolved = resolve_song_ids(song.get('name', ''), song.get('artist', ''))
                if resolved and resolved.get("encrypted_id"):
                    song['encrypted_id'] = resolved.get("encrypted_id")
                    if resolved.get("original_id") and not song.get('original_id'):
                        song['original_id'] = resolved.get("original_id")

        return jsonify({
            "success": True,
            "queue": queue,
            "total": data.get('total', len(queue))
        })
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@app.route("/debug/queue/raw", methods=["GET"])
def debug_queue_raw():
    returncode, stdout, stderr = run_ncm_raw(["queue"], "json")
    return jsonify({
        "success": returncode == 0,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }), (200 if returncode == 0 else 500)

@app.route("/debug/playlist/tracks/raw", methods=["GET"])
def debug_playlist_tracks_raw():
    playlist_id = request.args.get("id") or request.args.get("original_id") or request.args.get("encrypted_id") or ""
    if not playlist_id:
        return jsonify({"success": False, "error": "需要提供 id（或 original_id/encrypted_id）"}), 400
    returncode, stdout, stderr = run_ncm_raw(["playlist", "tracks", "--playlistId", str(playlist_id), "--limit", "500", "--offset", "0"], "json")
    return jsonify({
        "success": returncode == 0,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }), (200 if returncode == 0 else 500)

@app.route("/queue/add", methods=["POST"])
def queue_add():
    """
    添加到播放队列
    参数：url 或 id
    """
    data = request.json or {}
    url_or_id = data.get("url") or data.get("id", "")
    if not url_or_id:
        return jsonify({"error": "需要提供 url 或 id 参数"}), 400
    add_log(f"添加队列：{url_or_id}", "command")
    result = run_ncm(["queue", "add", url_or_id])
    add_log("队列：已添加歌曲", "status")
    return result

@app.route("/queue/clear", methods=["POST"])
def queue_clear():
    """清空播放队列"""
    add_log("清空队列", "command")
    result = run_ncm(["queue", "clear"])
    add_log("队列：已清空", "status")
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("ncm-cli HTTP 控制服务 v2.0")
    print("=" * 60)
    print("前端界面：http://localhost:8765")
    print("API 文档：http://localhost:8765/api/info")
    print("操作日志：http://localhost:8765/api/logs")
    print("=" * 60)
    app.run(host="0.0.0.0", port=8765, debug=True)
