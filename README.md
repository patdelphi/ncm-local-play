# ncm-local-play

基于 [ncm-cli](https://www.npmjs.com/package/@music163/ncm-cli) 的网易云音乐本地 Web 播放控制器。通过 Flask HTTP API 包装 ncm-cli 命令，提供浏览器端的音乐播放控制界面。

## 功能

- 歌单浏览与播放（收藏歌单、红心歌单）
- 每日推荐、私人 FM、私人雷达、心动模式
- 播放控制（播放/暂停/上下首/音量/进度跳转）
- 实时播放状态与队列同步
- 键盘快捷键（Space 播放/暂停、← → 切歌、↑ ↓ 音量、Esc 停止）
- 歌曲搜索与解析播放

## 前置要求

- Python 3.8+
- [ncm-cli](https://www.npmjs.com/package/@music163/ncm-cli) (`npm install -g @music163/ncm-cli`)
- [mpv](https://mpv.io/) 播放器
- Flask (`pip install flask`)

## 快速开始

```bash
# 1. 安装依赖
pip install flask
npm install -g @music163/ncm-cli

# 2. 配置 ncm-cli
ncm-cli configure
ncm-cli login

# 3. 启动服务
python ncm-api.py
```

浏览器打开 http://localhost:8765 即可使用。

## 项目结构

```
ncm-api.py            # Flask HTTP API 服务
templates/index.html   # Web 前端界面
tests/test_api.py      # 单元测试
ncm-cli/               # ncm-cli 本地副本
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/state` | GET | 获取播放状态 |
| `/play` | POST | 恢复播放 |
| `/pause` | POST | 暂停 |
| `/stop` | POST | 停止 |
| `/next` | POST | 下一首 |
| `/prev` | POST | 上一首 |
| `/volume/<level>` | POST | 设置音量 (0-100) |
| `/seek/<seconds>` | POST | 跳转进度 |
| `/playlist/play` | POST | 播放歌单 |
| `/recommend/daily/play` | POST | 播放每日推荐 |
| `/recommend/fm/play` | POST | 播放私人 FM |
| `/recommend/heartbeat` | POST | 心动模式 |
| `/search/song` | GET | 搜索歌曲 |
| `/login/status` | GET | 登录状态 |

完整 API 列表见 http://localhost:8765/api/info

## License

MIT
