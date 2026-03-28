<!--
程序说明：
- 本文档用于“先理解 ncm-cli 文档，再设计可复现测试场景”，避免猜测参数/字段。
- 原则：
  - 优先使用确定可获取数据的命令（help/commands/config/user/playlist/queue/state 等）。
  - 尽量不使用 search 作为数据来源（search 易受同名/版本/地区影响）。
  - 所有会改变播放状态/队列的命令单独标注为“非幂等”，默认不执行，需用户确认后再执行。
-->

# ncm-cli 测试场景与命令清单

## 0.1 已验证结论（本机实测）
- `playlist collected` 返回的每条 record 同时包含：
  - `id`：32 位 hex 字符串（作为 `--playlistId` 使用）
  - `originalId`：数字
- `playlist tracks` 的正确用法是 `--playlistId <hex>`，且返回结构为：
  - `code == 200`
  - `data` 为数组（不是 `data.records`/`data.tracks`）
  - `data[i].id` 为加密歌曲ID（32 位 hex）
  - `data[i].originalId` 为原始歌曲ID（数字）
  - `data[i].artists[]` 为歌手数组
- `playlist tracks` 不接受位置参数（传 `<id>` 会报 “Expected 0 arguments but got 1”）。

## 0. 约定与变量
- “加密歌单ID”：`playlistId`（通常为 32 位 hex 字符串），用于 `playlist tracks/get --playlistId ...`
- “原始歌单ID”：`originalId`（数字），常见于 `playlist collected` 返回
- “加密歌曲ID”：`encryptedSongId`（通常为 32 位 hex 字符串），常见于 `playlist tracks` 返回每首歌的 `id`
- “原始歌曲ID”：`originalSongId`（数字），常见于 `playlist tracks` 返回每首歌的 `originalId`

建议在 PowerShell 里用变量保存（示例，按实际输出填写）：
```powershell
$playlistId = "282148FBEB3B987D6195171772805F0D"
$playlistOriginalId = "6948804931"
```

## 1. 环境与可执行性（幂等）
### 1.1 基础信息
```powershell
ncm-cli --version
ncm-cli --help
ncm-cli commands
```

### 1.2 子命令 help（用来“确定参数”，禁止猜）
```powershell
ncm-cli play --help
ncm-cli playlist collected --help
ncm-cli playlist tracks --help
ncm-cli playlist get --help
ncm-cli queue --help
ncm-cli state --help
ncm-cli user info --help
```

### 1.3 PATH/可执行文件定位（幂等）
```powershell
Get-Command "ncm-cli"
where.exe "ncm-cli"
```

## 2. 登录态检查（幂等）
### 2.1 最可靠：user info
```powershell
ncm-cli user info --output json
```
期望：
- `code == 200`
- `data` 非空（包含昵称等）

### 2.2 辅助：login --check
```powershell
ncm-cli login --check --output json
```
说明：不同版本字段可能不一致，所以不要只靠某一个布尔字段判断。

## 3. 歌单列表与 ID 获取（幂等）
### 3.1 获取收藏歌单（确定拿到 playlistId/originalId）
```powershell
ncm-cli playlist collected --limit 5 --output json
```
期望每条 record 至少有：
- `id`（加密歌单ID/playlistId）
- `originalId`（原始歌单ID，数字）
- `name`、`trackCount`

如果 UI 里看不到 originalId，可直接以 `id` 为主完成 tracks/get。

## 4. 歌单曲目获取（幂等，关键）
### 4.1 playlist tracks（按 help：使用 --playlistId，不接收位置参数）
```powershell
ncm-cli playlist tracks --playlistId $playlistId --limit 30 --offset 0 --output json
```
期望：
- `code == 200`
- `data` 为数组
- 每个元素包含：
  - `id`（加密歌曲ID encryptedSongId）
  - `originalId`（原始歌曲ID originalSongId）
  - `name`
  - `artists[]`

### 4.2 playlist get（兜底）
```powershell
ncm-cli playlist get --playlistId $playlistId --output json
```
说明：若 tracks 因接口限制/分页失败，get 有时能返回部分信息（是否包含 tracks 取决于版本）。

## 5. 播放状态与队列观察（幂等）
### 5.1 state（只读）
```powershell
ncm-cli state --output json
```

### 5.2 queue（只读）
```powershell
ncm-cli queue --output json
```
说明：如果当前播放器/会话没有由 ncm-cli 管理的队列，可能返回“播放队列为空”，这会导致 Web UI 无法稳定显示队列。

## 6. 非幂等命令（默认不执行，需确认）
### 6.1 login（会触发登录流程）
```powershell
ncm-cli login
```

### 6.2 播放歌单（会改变播放状态/队列）
根据 `ncm-cli play --help`，歌单模式需要提供 `--encrypted-id/--original-id`。
注意：本机实测 `playlist tracks/get` 使用的是 `--playlistId <32位hex>`，这与 `play --help` 对“歌单加密ID”为数字的描述存在出入，因此“播放歌单”必须以实测为准，执行前先确认。

示例（仅示意，需确认后执行）：
```powershell
ncm-cli play --playlist --encrypted-id $playlistId --original-id $playlistOriginalId --output json
```

## 7. 与本项目 HTTP 服务对照测试（幂等为主）
### 7.1 登录状态（只读）
```powershell
Invoke-WebRequest "http://localhost:8765/login/status" | Select-Object -Expand Content
```

### 7.2 读取队列（只读）
```powershell
Invoke-WebRequest "http://localhost:8765/queue" | Select-Object -Expand Content
Invoke-WebRequest "http://localhost:8765/debug/queue/raw" | Select-Object -Expand Content
```

### 7.3 读取歌单 tracks 原始输出（只读）
```powershell
Invoke-WebRequest "http://localhost:8765/debug/playlist/tracks/raw?id=$playlistId" | Select-Object -Expand Content
```

## 8. 常见错误与对应结论（用于快速定位）
- `unknown option '--original-id'` / `Expected 0 arguments but got 1`
  - 结论：调用姿势不匹配当前版本 help，必须以 `--help` 输出为准，尤其是 `playlist tracks/get`。
- `播放队列为空`
  - 结论：当前会话没有可读队列；Web UI 依赖 queue 展示会出现“不一致/点不了”，需要明确“谁负责维护队列”（ncm-cli / 前端）。
