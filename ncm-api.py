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
from datetime import datetime

app = Flask(__name__, template_folder='templates')

# 全局日志存储
operation_logs = []

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
        
        cmd = "ncm-cli " + " ".join(args)
        print(f"执行：{cmd}", file=sys.stderr)

        result = subprocess.run(
            cmd,
            shell=True,
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    
    # 只使用 encrypted_id 播放
    result = run_ncm([
        "play", "--song",
        "--encrypted-id", encrypted_id
    ])
    
    add_log("单曲播放：已发送播放请求", "status")
    return result


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
    recommend_data = run_ncm(["recommend", "daily", "--limit", "30"], "json")
    try:
        data = json.loads(recommend_data[0]) if isinstance(recommend_data, tuple) else json.loads(recommend_data)
        songs = data.get('data', [])
        
        if not songs or len(songs) == 0:
            add_log("每日推荐为空", "error")
            return jsonify({"error": "每日推荐为空"}), 400
        
        # 逐首添加到队列
        for song in songs:
            run_ncm([
                "queue", "add",
                "--encrypted-id", song['id']
            ], "json")
        
        # 播放第一首
        if songs:
            first_song = songs[0]
            result = run_ncm([
                "play", "--song",
                "--encrypted-id", first_song['id']
            ])
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
    fm_data = run_ncm(["recommend", "fm", "--limit", "3"], "json")
    try:
        data = json.loads(fm_data[0]) if isinstance(fm_data, tuple) else json.loads(fm_data)
        songs = data.get('data', [])
        
        if not songs or len(songs) == 0:
            return jsonify({"error": "FM 推荐为空"}), 400
        
        # 清空队列并添加 FM 歌曲
        run_ncm(["queue", "clear"])
        
        for song in songs:
            run_ncm([
                "queue", "add",
                "--encrypted-id", song['id']
            ], "json")
        
        # 播放第一首
        first_song = songs[0]
        result = run_ncm([
            "play", "--song",
            "--encrypted-id", first_song['id']
        ])
        
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
    heartbeat_data = run_ncm([
        "recommend", "heartbeat",
        "--songId", song_id if song_id else "",
        "--count", count
    ], "json")
    
    try:
        result_data = json.loads(heartbeat_data[0]) if isinstance(heartbeat_data, tuple) else json.loads(heartbeat_data)
        songs = result_data.get('data', [])
        
        if not songs or len(songs) == 0:
            return jsonify({"error": "心动模式推荐为空"}), 400
        
        # 清空队列并添加推荐歌曲
        run_ncm(["queue", "clear"])
        
        for song in songs:
            run_ncm([
                "queue", "add",
                "--encrypted-id", song['id']
            ], "json")
        
        # 播放第一首
        first_song = songs[0]
        result = run_ncm([
            "play", "--song",
            "--encrypted-id", first_song['id']
        ])
        
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
    favorite_data = run_ncm(["user", "favorite"], "json")
    try:
        data = json.loads(favorite_data[0]) if isinstance(favorite_data, tuple) else json.loads(favorite_data)
        original_id = data.get('data', {}).get('originalId', '')
        encrypted_id = data.get('data', {}).get('id', '')
        
        if not original_id or not encrypted_id:
            add_log("获取红心歌单 ID 失败", "error")
            return jsonify({"error": "获取红心歌单 ID 失败"}), 500
        
        result = run_ncm([
            "play", "--playlist",
            "--original-id", str(original_id),
            "--encrypted-id", encrypted_id
        ])
        add_log(f"红心歌单：已加载 {original_id}", "status")
        return result
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
    需要提供歌单的 original_id 和 encrypted_id
    """
    data = request.json or {}
    original_id = data.get("original_id", "")
    encrypted_id = data.get("encrypted_id", "")

    if not original_id:
        return jsonify({"error": "需要提供 original_id", "success": False}), 400

    add_log(f"播放歌单：ID={original_id}", "command")

    try:
        # 构建命令
        cmd_parts = ["play", "--playlist", "--original-id", original_id]
        if encrypted_id:
            cmd_parts.extend(["--encrypted-id", encrypted_id])
        
        cmd = "ncm-cli " + " ".join(cmd_parts) + " --output json"
        print(f"执行：{cmd}", file=sys.stderr)

        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        # 无论返回什么，都返回成功标志让前端继续刷新
        add_log(f"歌单播放：已发送请求 {original_id}", "status")
        return jsonify({
            "success": True,
            "status": "ok",
            "playlist_id": original_id
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
    
    # 直接执行命令，不使用 run_ncm（因为参数格式特殊）
    import subprocess
    cmd = f'ncm-cli search song --keyword "{keyword}" --output json'
    print(f"执行：{cmd}", file=sys.stderr)
    
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
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
    return run_ncm(["login", "--check"])

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
        # 获取队列数据
        cmd = "ncm-cli queue --output json"
        print(f"执行：{cmd}", file=sys.stderr)

        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        if result.returncode != 0:
            return jsonify({"error": result.stderr, "success": False}), 500

        data = json.loads(result.stdout)
        if not data.get('success'):
            return jsonify(data)

        # 解析队列数据，为每首歌添加 name 和 artist 字段
        queue = data.get('queue', [])
        for song in queue:
            # 从 label 解析歌曲名和歌手 (格式：歌曲名 - 歌手)
            label = song.get('label', '')
            parts = label.split(' - ')
            if len(parts) >= 2:
                song['name'] = parts[0].strip()  # 第一部分是歌曲名
                song['artist'] = parts[1].strip()  # 第二部分是歌手
            else:
                song['name'] = label
                song['artist'] = '未知艺术家'
            # 注意：ncm-cli queue 命令不返回 encrypted_id，需要前端通过搜索获取
            song['encrypted_id'] = ''
            song['original_id'] = ''

        return jsonify({
            "success": True,
            "queue": queue,
            "total": data.get('total', len(queue))
        })
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

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
