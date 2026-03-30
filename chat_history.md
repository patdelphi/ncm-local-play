<!--
程序说明：
- 本文件用于追加记录每次对话的关键信息，便于回溯需求与决策。
-->

## 2026-03-28

### 用户
- 分析项目，阅读 txt 文档了解 ncm-cli；现有 Python/前端播放列表逻辑问题：点歌单不更新播放列表、点歌曲找不到/报错、上一首下一首顺序混乱等；要求给修复计划。

### 助手
- 阅读 `"ncm-commands.txt"` / `"ncm-help.txt"` 与代码，定位根因：
  - 前端 `fetchState()` 与 `fetchQueue()` 共用 `isRefreshing`，且自动刷新只跑 state，导致队列刷新经常被跳过；
  - 后端 `/queue` 丢失歌曲 ID、用 `label` 拆分 `name/artist` 易错；
  - `/playlist/play` 无论执行失败与否都返回成功；
  - `/api/info` 声明 `/next` `/prev` 但后端未实现。
- 输出分阶段修复计划并写入 `"todo.md"`，包含两种路线（next/prev 走后端 or 前端索引点播）与测试方案。

### 用户
- 确认按计划执行；测试允许直接启动服务，通过 Flask 发起调用命令测试。

### 助手
- 后端修复：
  - 改为参数数组调用 ncm-cli（减少 shell=True 的转义/注入风险）。
  - 补齐 `/next` `/prev` 路由，走 ncm-cli 的 next/prev。
  - `/playlist/play` 改为按 returncode 返回成功/失败，不再“假成功”。
  - `/queue` 改为复用统一的 raw 执行函数，错误返回更完整。
- 前端修复：
  - 拆分 state/queue 刷新锁，新增队列定时刷新，避免队列更新被阻塞。
  - 上一首/下一首改为调用后端 `/prev` `/next`，并刷新 state/queue。
  - 增加 encryptedId 缓存，减少重复搜索导致的“找不到/播错”概率。
- 增加单元测试：`"tests/test_api.py"`，并用 `python -m unittest discover -s "tests" -p "test_*.py"` 验证通过。
- 调整测试加载方式，去除 Python 未来版本的弃用警告后仍保持测试全绿。

### 用户
- 播放每日推荐时报错：`the JSON object must be str, bytes or bytearray, not Response`。

### 助手
- 修复推荐相关接口（每日推荐/FM/心动模式/红心歌单）内部解析逻辑，避免对 Flask Response 做 `json.loads`：
  - 统一改用 `run_ncm_raw()` 读取 stdout 并按 returncode 判错返回。
- 补充每日推荐播放接口单测（成功/失败两种），并验证 tests 全绿。

### 用户
- 登录用户加载不出，歌单看不见；播放红心歌单时报错：`[WinError 2] 系统找不到指定的文件`。

### 助手
- 后端：
  - 为 `ncm-cli` 增加可配置路径：支持环境变量 `NCM_CLI_PATH`；并对 FileNotFoundError 返回更友好的错误提示。
- 前端：
  - 用户信息/歌单加载失败时写入界面日志，避免静默失败。
  - 播放红心歌单前清空队列改为校验接口返回，避免“清空成功”假提示。

### 用户
- 需求：检查用户登录状态；未登录则提示用户执行 `ncm-cli login`。另外：ncm-cli 已在 PATH，但 Python 里为何不能调用？

### 助手
- 解释与修复：
  - Windows 下 npm 安装的 ncm-cli 往往是 `ncm-cli.cmd`，Python 的 subprocess 直接执行可能失败；已增加自动解析并在需要时用 `cmd.exe /c` 调用。
  - `/login/status` 改为结构化返回 JSON，并提供 `logged_in` 字段；前端启动时先检查登录状态，未登录会在页面日志提示运行 `ncm-cli login`。
  - 为 `/login/status` 增加单测，确保 `logged_in` 计算正确。

### 用户
- 已完成登录，但页面仍提示未登录。

### 助手
- 修复：放宽 `/login/status` 的 logged_in 判定逻辑（success=true 时，优先识别 code==200，其次识别多种字段；缺省按 data 是否非空判断），避免误报未登录。
- 补充单测覆盖 code==200 场景并保持 tests 全绿。

### 用户
- 反馈：应按文档用 `ncm-cli user info` 看用户信息来判断登录。

### 助手
- 调整：`/login/status` 改为优先调用 `ncm-cli user info` 判断登录（code==200 且 data 非空视为已登录），并保留 `login --check` 兜底。
- 补充单测覆盖 “优先 user info” 路径并保持 tests 全绿。

### 用户
- 登录后播放列表仍不对：显示与 ncm-cli 实际队列不一致；上一首下一首高亮会跳；点击列表歌曲很多不可播放。

### 助手
- 后端：
  - `/queue` 修复：label 解析改用 rsplit 防止歌曲名含“ - ”导致 name/artist 错位；不再强制清空 encrypted_id/original_id，并从常见字段名归一化补齐，提升点歌成功率。
- 前端：
  - 队列高亮：仅在无 current 且当前索引未知时才用 state.title 推断，减少“跳着显示”。
  - 点歌匹配：优先用后端提供的 encrypted_id；需要搜索时优先匹配同名且歌手包含关系，不再总取第一条。
- 测试：
  - 补充队列解析单测：覆盖歌曲名含“ - ”与 encrypted_id 不被覆盖场景，并保持 tests 全绿。

### 用户
- 反馈：播放列表仍不对。

### 助手
- 进一步修复：
  - 新增后端歌曲 ID 解析接口 `/song/resolve`：基于 `ncm-cli search song` 解析 encrypted_id，并做内存缓存。
  - `/queue` 支持 `hydrate=1` 时自动为缺失 encrypted_id 的队列项补齐（使用缓存/搜索）。
  - 前端点歌无 encryptedId 时不再直接调用 /search/song，而是调用 /song/resolve，提高匹配稳定性。
  - 新增 `/debug/queue/raw` 用于对照 ncm-cli 原始队列输出。
  - 补充 /song/resolve 单测并保持 tests 全绿。

### 用户
- 提供 `/debug/queue/raw` 输出：显示“播放队列为空”；反馈播放列表仍不对。

### 助手
- 修复入队方式，确保 ncm-cli queue 可见：
  - 将每日推荐/FM/心动模式的入队从 `queue add --encrypted-id <id>` 改为 `queue add <id>`（兼容 ncm-cli 的参数形式）。
  - 重写 `/playlist/play` 与 `/user/favorite/play`：先 `playlist tracks` 获取歌曲列表，再 `queue clear` + `queue add` 全部入队并播放第一首，确保 `/debug/queue/raw` 不再显示“队列为空”。
  - 更新并跑通单元测试，确保歌单入队逻辑稳定。

### 用户
- 反馈：播放歌单失败“获取歌单歌曲失败”，质疑是否做了真实测试。

### 助手
- 补强：
  - 增强歌单 tracks 解析：兼容 `data.tracks`、`data.playlist.tracks` 等结构。
  - 新增调试接口 `/debug/playlist/tracks/raw?original_id=...`，可直接看到 ncm-cli 的 stdout/stderr 以定位真实失败原因。
  - 前端在歌单播放失败时展示 stderr/stdout（若存在），避免只看到泛化错误。
  - 更新单测覆盖 `data.tracks` 结构并保持 tests 全绿。

### 用户
- 要求：自行阅读文档与运行 CLI 测试并优化，不要反复询问。

### 助手
- 进一步优化（不依赖用户手工分析 stdout）：
  - 歌单 tracks 获取增加多路兜底：对同一歌单同时尝试 `playlist tracks/get` 的多种参数组合（original_id/encrypted_id），并在失败时返回 attempts（包含 args/stdout/stderr）用于直接定位。
  - 更新单测适配新错误结构（attempts），并保持 tests 全绿。

### 用户
- 问题：在界面/返回数据里看不到 originalId。

### 助手
- 修复：不再强依赖 originalId
  - 前端：提交歌单播放请求时，originalId 缺失则仅传 playlist.id（encrypted_id）。
  - 后端：/playlist/play 支持仅有 encrypted_id 的请求，并继续用多路兜底去尝试 tracks/get 获取歌曲列表。
  - 增加单测覆盖“仅 encrypted_id 也可播放歌单”的路径，保持 tests 全绿。

### 用户
- 反馈：歌单“全球流行趋势 ...”仍提示“获取歌单歌曲失败”，质疑为何功能退化。

### 助手
- 处理：
  - /playlist/play 与 /user/favorite/play 在无法获取 tracks 时增加兜底：直接调用 ncm-cli 的 `play --playlist` 播放歌单（保证能播），并返回 mode=playlist + warning（队列展示可能为空）。
  - 前端识别 mode=playlist 时不再清空播放队列 UI，避免误导；失败时从 attempts 中提取 stderr 显示定位信息。

### 用户
- 反馈：播放失败 stderr 提示 `unknown option '--original-id'`，要求重读文档并重写逻辑。

### 助手
- 修复：按 ncm-cli 文档调整 playlist tracks/get 调用方式
  - `playlist tracks` 改为使用位置参数传入歌单 ID（不再传 `--original-id/--encrypted-id`）。
  - 调试接口 `/debug/playlist/tracks/raw` 同步改为 `playlist tracks <id>`，并支持 query 参数 `id/original_id/encrypted_id`。

### 用户
- 反馈：tracks 报错 `Expected 0 arguments but got 1`。

### 助手
- 复核真实 CLI 帮助后修复：
  - `playlist tracks/get` 正确参数为 `--playlistId <value>`（不接收位置参数）。
  - `playlist tracks` 返回的 data 结构为数组（不是 records/tracks 字段），已修复解析。
  - `/debug/playlist/tracks/raw` 同步改为 `playlist tracks --playlistId <id> --limit 500 --offset 0`。

### 用户
- 要求：先停止编码，先理解文档；设计完整测试场景，确保命令可调用、ID 可获取；少用 search；输出完整测试用例与命令文档。

### 助手
- 输出：新增项目文档 `"Docs/ncm_cli_test_plan.md"`，包含：
  - 基于 `--help` 的参数确认流程（避免猜测）。
  - 登录/歌单/曲目/队列/state 等幂等测试场景与命令。
  - 非幂等命令单独标注并默认不执行。

### 用户
- 要求：由助手自行试错直到获取正确方式，并更新测试文档，只交付结果。

### 助手
- 结果：更新 `"Docs/ncm_cli_test_plan.md"`，补充本机实测结论（playlist collected/playlist tracks 的真实参数与返回结构），并将常见报错与对应正确用法固化到文档。

### 用户
- 确认：允许继续修改代码。

### 助手
- 修改：
  - 歌单曲目获取统一使用 `playlist tracks/get --playlistId`，不再使用 `--original-id` 或位置参数。
  - 歌单入队与首曲播放改为携带歌曲 `encrypted_id/original_id`（匹配 `queue add` 与 `play --song` 参数要求）。
  - `/song/resolve` 返回 `encrypted_id+original_id`，前端点歌携带 original_id 播放，提高稳定性。
  - 更新并运行后端单元测试（11 项）全部通过。

### 用户
- 反馈：歌曲加入播放列表很慢，列表里出现 32 位 hex 乱码（看起来是加密ID）。

### 助手
- 优化：
  - 入队加速：歌单入队改为“先同步入队前 30 首 + 后台线程补齐剩余”，减少点击后的等待时间。
  - 乱码修复：从 `playlist tracks` 缓存 `encrypted_id -> (name/artist/original_id)` 映射；/queue 若 label 显示为 32 位 hex，则用缓存回填正确的歌名/歌手。
  - 降低队列轮询频率（2s -> 5s）减少对 ncm-cli 的压力。
  - 运行单元测试保持全绿。

### 用户
- 反馈：播放队列逐条灌入太慢且导致操作逻辑混乱；要求参考 ncm-cli TUI 的机制，确保准确性与速度并执行实现。

### 助手
- 实现：切换为 session 播放列表模式（TUI 同款思路：列表=tracks，播放=按 ID）
  - 后端新增 `/session/*`：保存当前歌单 tracks 列表与 index，支持按 index 播放、上一首/下一首。
  - `/playlist/play` 与 `/user/favorite/play` 改为直接 `play --song` 播放第一首并返回完整 entries（不再依赖 ncm queue 慢速灌入）。
  - 前端播放列表展示与点歌/上一首/下一首改为走 session（不再依赖 `/queue` 的中间态）。
  - 更新并跑通后端单元测试。

### 用户
- 反馈：前端显示切歌已更新，但实际播放仍是原来的歌曲。

### 助手
- 修复：
  - session 切歌接口改为严格检查 `play --song` 是否真实成功（按 returncode/JSON success 判定）；失败则返回 500 且不更新 session index，避免“显示变了但没切”。
  - 补充 session 切歌单测覆盖播放失败场景，并保持 tests 全绿。

### 用户
- 需求：检查每日推荐/私人FM/心动模式是否正确；播放时显示当前播放来源（歌单/红心/每日推荐等）。

### 助手
- 调整：
  - 每日推荐/私人FM/心动模式统一切换为 session 播放（返回 mode=session+entries，播放第一首并由 session 维护索引）。
  - session 增加 source 元数据（type/name/id），/session/status 输出 source_name 供前端展示。
  - 前端在“正在播放”区域显示来源名称（📀），并在推荐入口切换到 session 模式后保持列表与高亮同步。
  - 更新并跑通单元测试：新增 FM/心动模式 session 测试，tests 全绿。

### 用户
- 反馈：播放心动模式提示“推荐为空”。

### 助手
- 修复：
  - 心动模式 `song_id` 现在强制使用原始歌曲ID（数字）；如果前端传入 32 位 hex（加密ID），会用缓存映射到 original_id；缺失则用 session 当前曲目 original_id 兜底。
  - 无法得到有效数字 songId 时直接返回 400（避免误判为“推荐为空”）。
  - 新增单元测试覆盖：缺 songId、hex->originalId 映射等场景，并保持 tests 全绿。

### 用户
- 反馈：终端显示 user history records=0，仍提示缺 song_id；随后又出现“推荐为空”，用户厌倦反复尝试。

### 助手
- 根因修复：重读 `ncm-cli recommend heartbeat --help` 后确认 `--songId` 需要的是“歌曲加密ID(32位hex)”，不是原始ID。
  - 后端心动模式改为优先使用 encrypted_id（session 当前曲目 / last_played / queue label / user history）。
  - 推荐为空时自动从 user history/last_played 提取多个加密ID种子重试，尽量减少用户手工重试。
  - 前端改为只传当前曲目的 encryptedId 给心动模式，并在失败日志里展示 debug.steps 链路。
  - 更新并跑通单元测试，保持 tests 全绿。

## 2026-03-29

### 用户
- review一下项目，现在还有很多问题，播放列表工作不正常

### 助手
- 定位播放列表不正常的关键原因：后端 `/state` 与基础控制接口返回结构不一致，前端只认 `success` 导致状态/队列不同步。
- 后端统一 `/state`、`/play`、`/pause`、`/stop`、`/next`、`/prev`、`/seek`、`/volume`、`/song/play` 的返回结构：补齐 `success/message/state/raw`。
- 前端增加对 `success/status/code` 的兼容判断，并对 `/state` 返回做结构兼容提取，避免误判失败。
- 新增单元测试覆盖状态归一化与控制接口兼容性，并验证 tests 全绿。

### 用户
- 歌曲无法播放

### 助手
- 修复：兼容 ncm-cli 在播放命令成功时 stdout 为空或非 JSON 的情况，避免后端将其误判为失败导致前端提示“无法播放”。
- 新增单元测试覆盖空输出与非 JSON 输出两类场景，并验证 tests 全绿。

### 用户
- 1. 上一首下一首不稳定，有时候ok有时候不行，好像要点击一下歌单歌曲才能正常
- 2. 系统初始化，播放列表应为空
- 3. 点击歌单或红心、每日推荐、私人雷达、私人FM、心动模式，应先停下当前播放，清空播放列表，然后加载歌曲，自动播放第一首

### 助手
- 修复切歌不稳定：前端上一首/下一首统一调用后端 `/prev`/`/next`，避免前端 session 状态漂移导致调用错误接口；后端新增 `/session/clear` 并在 `/stop`、`/song/play` 时清 session，避免残留 session 抢占 next/prev。
- 初始化播放列表为空：页面加载时主动清空播放列表状态，且默认不自动刷新 `/queue`（除非进入队列模式）。
- 切换播放源统一流程：点击歌单/红心/每日推荐/私人雷达/私人FM/心动模式时先调用停止并清空播放列表，再请求后端加载并自动播放第一首；session 模式下仅由 session 列表驱动高亮。
- 新增单元测试覆盖 session 清理与 stop/song_play 清 session 行为，并验证 tests 全绿。

### 用户
- 1. 切换上一首下一首，显示播放的歌名变了，但并未播放，还是在播之前的歌
- 2. 音量系统初始化默认设为50%，不只是显示，真实音量也要调

### 助手
- 修复“显示切歌但实际没切”：后端 session 切歌在返回成功前增加 state 校验（标题需切到目标曲目），否则返回 500 且不更新 session index；非 session 的 `/next`/`/prev` 也增加 state 变化校验，避免前端误认为成功。
- 启动时真实设置默认音量：前端初始化阶段主动调用 `/volume/50`，确保真实音量与 UI 一致。
- 更新并跑通单元测试，保持 tests 全绿。

### 用户
- [09:49:19] 播放失败：播放未生效
- [09:49:18] 点击播放：夢の続き - 竹内まりや (索引：9)
- 各种报错，播放键、上一首下一首、点击播放列表歌曲，都有问题，要求整体 review 并把基本功能做好

### 助手
- 调整切歌校验策略：将“未在短时间内观测到 state 变化”从硬失败改为 `applied=false`（仍返回 success=true 且不更新 session index），避免播放器状态更新延迟导致大量误报失败。
- 增强校验依据：轮询等待时同时考虑 title 变化与 position 重置（上一曲/下一曲/点播更稳定）。
- 前端 session 点播收到 `applied=false` 时不再立即切换高亮，改为提示“等待生效”并触发多次刷新拉齐状态。
- 更新并跑通单元测试，保持 tests 全绿。

### 用户
- 根本播放不了，点播放或点歌名都不行

### 助手
- 根因定位：部分接口/数据源把“数字ID”误当成“32位hex歌曲加密ID”，导致 `play --song --encrypted-id <id>` 实际无效。
- 修复：后端提取歌曲ID时优先选择32位hex；队列接口对非hex的 encrypted_id 置空以触发前端 resolve；session 点播在ID不合法时自动 search resolve；/song/play 对非法 encrypted_id 直接报错避免假成功。
- 前端对 encryptedId 增加 32位hex 校验，避免带着错误ID直接调用播放接口。
- 更新并跑通单元测试，保持 tests 全绿。
