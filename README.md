# 一骑红尘：荔枝争运战 Python 服务端

这是根据根目录任务书和通信协议实现的本地调试服务端。服务端使用 Python 标准库编写，按比赛协议通过 TCP Socket 与两个客户端通信。

## 环境要求

- Python 3.12 或兼容版本
- 不需要安装第三方依赖

## 启动服务端

在项目根目录运行：

```bash
python server.py --host 0.0.0.0 --port 8081
```

常用参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `0.0.0.0` | 服务端监听地址 |
| `--port` | `8081` | 服务端监听端口 |
| `--tick-ms` | `500` | 每个结算帧等待客户端提交 `action` 的毫秒数 |
| `--duration-round` | `600` | 最大结算帧数 |
| `--seed` | `20260630` | 本地确定性种子 |
| `--log-dir` | `logs` | 日志输出目录 |
| `--allowed-player-ids` | `1001,1002` | 允许注册的 playerId，逗号分隔；传空字符串表示允许任意两个 |
| `--verbose` | 关闭 | 在控制台输出更详细日志 |

示例：

```bash
python server.py --host 127.0.0.1 --port 9000 --tick-ms 500 --verbose
```

## 启动客户端

服务端启动后，会等待两个客户端连接并发送 `registration`。

本仓库提供了一个只发送空动作的调试客户端：

```bash
python idle_client.py 1001 127.0.0.1 8081
```

这个客户端不会主动移动或得分。它的行为是：

1. 连接服务器并发送 `registration`
2. 收到 `start` 后发送 `ready`
3. 每次收到 `inquire` 后发送 `actions: []`
4. 收到 `over` 后退出

如果你的客户端使用任务书要求的 `start.sh`，启动格式通常是：

```bash
./start.sh <playerId> <host> <port>
```

例如：

```bash
./start.sh 1001 127.0.0.1 8081
./start.sh 1002 127.0.0.1 8081
```

两名客户端都完成注册后，服务端会下发 `start`。双方继续发送 `ready` 后，服务端开始逐帧下发 `inquire` 并接收 `action`。

## 连续拉起两名客户端对战

`match_loop.py` 用于反复执行“启动服务器 -> 启动两个客户端 -> 等待比赛结束 -> 复制复盘文件 -> 等待双方分析完成 -> 下一局”。

通知机制默认使用文件标记。每局结束后，循环器会把干净复盘文件复制到 `--replay-out-dir`，并在同一目录写入一个 manifest：

```text
match_0001_<matchId>.replay.jsonl
match_0001_<matchId>.replay.manifest.json
```

manifest 里会写明 replay 路径，以及双方需要创建的完成标记：

```json
{
  "replay": "D:\\replays\\match_0001_xxx.replay.jsonl",
  "clientA": {
    "playerId": "1001",
    "doneFile": "D:\\replays\\match_0001_xxx.replay.client_a.done"
  },
  "clientB": {
    "playerId": "1002",
    "doneFile": "D:\\replays\\match_0001_xxx.replay.client_b.done"
  }
}
```

双方分析工具完成后，只要创建各自的 `doneFile` 即可，文件内容可以为空。两个标记都出现后，循环器自动开始下一局。

推荐先填写根目录的 `match_loop_config.json`，然后启动：

```powershell
python -B match_loop.py --config match_loop_config.json
```

配置文件是标准 JSON，不能写注释。命令行参数会覆盖配置文件里的同名字段，例如临时只跑 3 局：

```powershell
python -B match_loop.py --config match_loop_config.json --max-matches 3
```

示例，两个客户端都由启动脚本启动：

```powershell
python -B match_loop.py `
  --client-a-cmd 'bash D:/team_a/start.sh {player_id} {host} {port}' `
  --client-b-cmd 'bash D:/team_b/start.sh {player_id} {host} {port}' `
  --client-a-cwd 'D:/team_a' `
  --client-b-cwd 'D:/team_b' `
  --client-a-player-id 1001 `
  --client-b-player-id 1002 `
  --replay-out-dir 'D:/match_replays' `
  --run-root 'match_runs/loop' `
  --tick-ms 500 `
  --max-matches 0
```

`--max-matches 0` 表示一直循环。`--stop-file stop.loop` 可以指定停止文件；等待分析期间或下一局开始前发现该文件存在，就会停止。

运行中会定期打印状态，例如服务器和两个客户端是否仍在运行。间隔由配置里的 `status_interval` 控制，单位秒；设为 `0` 可关闭周期状态日志。每局的原始日志在 `run_root/<runId>/` 下：

```text
server.stdout.log / server.stderr.log
client_a.stdout.log / client_a.stderr.log
client_b.stdout.log / client_b.stderr.log
server_logs/server_*.log
```

如果任一客户端在比赛结束前异常退出，循环器会立即在控制台打印该客户端 stderr/stdout 的末尾内容，并终止本局。

客户端命令模板支持这些占位符：

| 占位符 | 说明 |
| --- | --- |
| `{player_id}` | 当前客户端自己的 playerId |
| `{player_id_a}` / `{player_id_b}` | A/B 双方 playerId |
| `{host}` / `{port}` | 本局服务器地址和端口 |
| `{match_index}` | 从 `--start-index` 开始递增的局号 |
| `{run_id}` | 本局运行目录名 |
| `{run_dir}` | 本局原始日志目录 |
| `{replay_dir}` | 复盘文件输出目录 |

如果你已经有分析命令，也可以交给循环器执行。分析命令返回 0 后，循环器会自动写对应的 `.done` 标记：

```powershell
python -B match_loop.py `
  --client-a-cmd 'bash D:/team_a/start.sh {player_id} {host} {port}' `
  --client-b-cmd 'bash D:/team_b/start.sh {player_id} {host} {port}' `
  --client-a-analysis-cmd 'python -B tools/analyze_replay.py "{replay}" --player-id {player_id}' `
  --client-b-analysis-cmd 'python -B tools/analyze_replay.py "{replay}" --player-id {player_id}' `
  --client-a-cwd 'D:/team_a' `
  --client-b-cwd 'D:/team_b' `
  --replay-out-dir 'D:/match_replays'
```

分析命令额外支持 `{replay}`、`{manifest}`、`{done_file}` 三个占位符。

## 通信协议

所有 TCP 消息都使用：

```text
5 位十进制长度前缀 + UTF-8 JSON body
```

客户端上行消息：

| 消息 | 说明 |
| --- | --- |
| `registration` | 注册 `playerId`、`playerName`、`version` |
| `ready` | 客户端收到并处理 `start` 后确认准备完成 |
| `action` | 按当前 `inquire.round` 提交动作 |

服务端下行消息：

| 消息 | 说明 |
| --- | --- |
| `start` | 对局、地图、资源、任务模板和玩家阵营 |
| `inquire` | 当前公开状态、上一帧事件和动作结果 |
| `over` | 最终结算结果 |
| `error` | 协议错误或当前消息未进入规则结算 |

## 日志

服务端默认把日志写入 `logs/`：

| 文件 | 说明 |
| --- | --- |
| `server_YYYYMMDD_HHMMSS.log` | 可读运行日志，包含连接、注册、每帧摘要和结束结果 |
| `<matchId>.audit.jsonl` | 结构化审计日志，每行一个 JSON 记录 |
| `<matchId>.replay.jsonl` | 干净复盘日志，只包含服务端下发的 `start/inquire/over/error` 消息 |

审计日志会记录：

- 客户端上行完整消息
- 服务端下行完整消息
- 每帧收到和缺失动作的玩家
- 每个动作的判定结果
- 每帧公开事件、玩家状态和节点状态
- 最终胜负和计分详情

给正常客户端的复盘工具使用时，优先使用 `<matchId>.replay.jsonl`。排查通信细节、动作原文和判决过程时，再查看 `<matchId>.audit.jsonl`。

## 运行测试

```bash
python -B -m unittest -v
```

`-B` 用于避免 Python 写入 `__pycache__`，在部分 Windows 目录权限受限时更稳。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `server.py` | Python 服务端主程序 |
| `idle_client.py` | 只发送空动作的测试客户端 |
| `match_loop.py` | 连续拉起服务器和两个客户端对战的循环器 |
| `match_loop_config.json` | 连续对战配置模板，填写两个客户端脚本、工作目录和复盘输出目录 |
| `start.sh` | 比赛平台格式的客户端启动脚本 |
| `test_server.py` | 单元测试和端到端通信测试 |
| `服务器使用说明.md` | 更详细的中文使用说明 |
| `一骑红尘：荔枝争运战 参赛选手任务书.md` | 比赛任务书 |
| `一骑红尘：荔枝争运战 通信协议.md` | 客户端和服务端通信协议 |
