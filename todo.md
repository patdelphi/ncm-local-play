<!--
程序说明：
- 本文件用于记录 ncm-local-play 的问题排查结论与修复执行清单（面向“播放列表/歌单/上一首下一首/点歌报错”等问题）。
- 你确认后我会按清单逐项实现与验证（会补测试，且只运行 lint/test/type-check/build 等幂等校验）。
-->

# 修复计划（ncm-local-play）

## 0. 当前结构（简要）
- 后端：Flask 服务 [`"ncm-api.py"`]，通过 `subprocess` 调用 `ncm-cli`
- 前端：单页 [`"templates/index.html"`]，通过 `/queue` 拉取队列并在浏览器维护 `currentPlaylist/currentPlayIndex`

## 1. 已确认的关键问题（根因）
1) 前端刷新锁使用不当  
   - `fetchState()` 与 `fetchQueue()` 共用 `isRefreshing`，且自动刷新只调用 `fetchState()`  
   - 结果：点歌单后定时触发的 `fetchQueue()` 经常被直接 return；队列无法稳定更新，导致“歌单点了但播放列表不变/为空”

2) 队列数据不可稳定点播  
   - 后端 `/queue` 主动把 `encrypted_id/original_id` 置空，只返回 `label` 再拆 `name/artist`  
   - 结果：前端只能用“歌名+歌手”再 `/search/song` 找第一条来播放，容易播错/找不到/顺序混乱

3) 歌单播放接口返回假成功  
   - `/playlist/play` 无论 `ncm-cli` 是否失败都返回 `success: true`  
   - 结果：前端认为成功并清空本地列表，随后队列刷新又失败或被跳过，体感“点击无效”

4) API 文档与实现不一致  
   - `/api/info` 宣称存在 `/next` `/prev`，但后端未实现路由

5) 可靠性与安全隐患（顺带修）  
   - 多处 `shell=True` + 字符串拼接（keyword/ID 未做转义），存在命令注入与引号破坏风险  
   - `run_ncm()` 返回类型不一致（成功字符串 / 失败 tuple），容易在调用处写出脆弱逻辑

## 2. 目标行为（修复验收标准）
- 点击歌单：后端真实切到该歌单，前端播放队列在 1-3 次刷新内稳定更新
- 点击队列歌曲：不会“找不到/报错”，且播放的是队列中的那一首
- 上一首/下一首：行为稳定，可连续切歌，索引与当前播放一致
- 接口失败时：前端提示明确错误，不再出现“假成功”

## 3. 两种实现路线（你选其一）
### 方案 A（推荐）：后端走 ncm-cli 的 next/prev 与队列“当前项”
- 前端：上一首/下一首调用 `/next` `/prev`，并强制刷新 `/queue`
- 后端：补齐 `/next` `/prev`，并让 `/queue` 透出“当前播放项标识”
- 优点：与播放器状态一致，不依赖前端索引推断
- 风险：依赖 `ncm-cli queue` 是否稳定返回 current 标记或可匹配字段

### 方案 B：继续前端按索引点播，但把“索引与队列”做稳定
- 前端：修复 `isRefreshing` 竞争；增加队列定时刷新；当 `/queue` 不含 current 时保留现有 `currentPlayIndex`
- 后端：改造 `/queue` 输出，提供足够字段让前端稳定匹配（至少要有可复现的 songId）
- 优点：不依赖 next/prev；交互更“播放器无关”
- 风险：如果队列里没有 songId，只能搜索匹配，会不可避免有误差

## 4. 分阶段修复清单（按优先级）
### Phase 1：先让播放列表“必然能更新”
- [ ] 前端把 `isRefreshing` 拆成 `isFetchingState/isFetchingQueue`，避免互相阻塞
- [ ] 增加队列定时刷新：例如每 2-3 秒 `fetchQueue()`（或在 state 变化时触发一次）
- [ ] `/playlist/play`：根据 `returncode` 返回 `success: false` + `stderr/stdout`，前端不再清空列表造成“假空”

### Phase 2：让点歌与切歌稳定
- [ ] 后端补齐 `/next` `/prev`（或明确前端继续索引点播的路线）
- [ ] `/queue`：尽量返回可用于点播的 ID（若 ncm-cli 本身不提供，考虑在后端缓存“label -> 最近一次 search 的 id”，降低找不到概率）
- [ ] 前端：`currentPlayIndex` 的计算改为优先 current 标记，其次用 state.title/label 近似匹配，最后保留原索引

### Phase 3：清理可靠性/安全问题（不影响功能但建议做）
- [ ] 统一 `run_ncm()` 返回：始终返回 JSON（包含 success/returncode/stdout/stderr）
- [ ] 去掉 `shell=True`，改用参数数组调用 `subprocess.run(["ncm-cli", ...])` 并做异常处理
- [ ] 统一搜索接口返回结构，避免前端字段名不一致导致“找不到”

## 5. 测试与验证（会补）
- 后端：用 Flask test client + mock `subprocess.run`，覆盖：
  - `/playlist/play` 成功/失败返回
  - `/queue` 解析与字段完整性
  - `/next` `/prev` 路由存在且错误处理正确
- 前端：至少加一个“最小自测脚本/手工验证清单”，确保队列刷新与索引稳定

## 6. 你需要确认的一个选择
请确认：上一首/下一首最终希望走哪种？
- A：调用 `ncm-cli next/prev`（推荐）
- B：继续前端按索引点播

