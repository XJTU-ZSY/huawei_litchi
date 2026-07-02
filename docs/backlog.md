# Backlog

## P0 已启动

### 000. 提交前质量门禁

Priority: P0

Expected behavior:
- 一条命令运行单元测试、打包和提交 ZIP 结构检查。
- 可选输入回放文件，检查被拒绝和非法动作数量。
- 门禁失败时不允许提交策略改动。

Validation:
- `python -B tools/quality_gate.py`

Status: done

### 000A. 回放目录自动监控

Priority: P0

Expected behavior:
- 监控指定回放目录中新出现且已稳定写完的回放文件。
- 自动生成回放分析报告和 coach 需求卡。
- 默认输出到 `.replay_watch/`，避免持续污染 git。
- 可选 `--append-backlog` 将需求卡追加到 `docs/backlog.md`。

Validation:
- `python -B tools/watch_replays.py <folder> --player-id <playerId> --once`
- `python -B tools/quality_gate.py`

Status: done

### 000B. 单轮流程日志

Priority: P0

Expected behavior:
- 每一轮回放分析生成独立 process log。
- 需求卡、实现计划、代码变更、测试结果、quality gate、git commit 都能追加到同一日志。
- skill handoff prompt 明确要求 replay analyst、coach、implementer、tester 更新流程日志。

Validation:
- `python -B tools/watch_replays.py <folder> --player-id <playerId> --once`
- `python -B tools/process_log.py <log> --stage Tests --message "..."`
- `python -B tools/quality_gate.py`

Status: done

### 000C. Replay manifest doneFile marker

Priority: P0

Evidence: replay optimization harness writes latest `*.manifest.json` in `replay_out_dir` with `clientA.doneFile` and `clientB.doneFile`.

Expected behavior:
- After replay-driven AI optimization succeeds, scan `replay_out_dir` for the latest `*.manifest.json`.
- Do not derive a literal `<replay-stem>.replay.manifest.json`; the manifest follows the replay filename with `.jsonl` replaced by `.manifest.json`.
- Create doneFile marker(s) in the replay directory using the `doneFile` values from `clientA` and `clientB`.

Forbidden behavior:
- Treating `*.manifest.json` as a replay input.
- Writing doneFile paths outside `replay_out_dir`.
- Marking done after a failed AI optimization command.

Implementation owner: `$litchi-architect -> $litchi-implementer -> $litchi-tester`

Validation:
- `python -B -m unittest`
- `python -B tools/quality_gate.py`
- `python -B tools/mark_replay_done.py <replay_out_dir>`

Status: done

### 001. 最小可运行 Python 客户端

Priority: P0

Evidence: 通信协议要求 `registration -> start -> ready -> inquire/action -> over`，每帧即使无动作也必须发送 `actions: []`。

Expected behavior:
- 通过 5 位长度前缀收发 JSON。
- 收到 `start` 后识别本方、地图、起点、宫门、终点。
- 收到 `inquire.round = N` 后发送 `action.round = N`。
- 决策异常时发送空动作心跳。

Validation:
- `python -m unittest`

Status: in progress

### 002. P0 保守策略

Priority: P0

Expected behavior:
- 移动中继续朝 `nextNodeId` 前进。
- 处理中、休整中、强制通行中不提交冲突主动作。
- 到 S14 且 RUSH 阶段未验核时提交 `VERIFY_GATE`。
- 到 S15 且已验核时提交 `DELIVER`。
- 当前节点有可做任务时优先 `CLAIM_TASK`。
- 当前节点有高价值资源时可 `CLAIM_RESOURCE`。

Forbidden behavior:
- 已交付后提交主动动作。
- 同帧提交两个主车队动作。
- 对未参与窗口乱出牌。

Validation:
- 决策单测覆盖关键状态。

Status: in progress

## P1 待办

### 101. 任务收益模型

目标：选择能让普通任务基础分达到 90 的最短可行任务组合。

### 102. 资源收益模型

目标：快马、短程马、冰鉴、情报按路线和阶段动态估值。

### 103. 终局急策

目标：在 RUSH 阶段决定 `RUSH_SPEED`、`RUSH_PROTECT` 或绑定 `BREAK_ORDER` 的使用时机。

## P2 待办

### 201. 窗口出牌策略

目标：根据对手历史出牌和资源成本选择窗口牌。

### 202. 对手路线学习

目标：从回放统计对手常走路线、任务优先级和设卡点。
