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

### 000D. 服务端错误根因与防重犯闭环

Priority: P0

Evidence: 用户要求“收到服务器返回的错误后，要重点审视原因，改进算法和代码，尽可能不重犯”。

Expected behavior:
- `$litchi-coach` 和 `$litchi-replay-analyst` 将 `msg_name:error`、`ACTION_REJECTED`、`INVALID_ACTION`、`actionResults.accepted=false` 视为 P0 证据，优先于得分优化。
- 每个服务端错误都要在复盘中写明触发帧、动作、错误码、根因、需要改进的算法/代码位置和回归验证。
- 需求卡完成前，必须能用单测、mock 状态或同一回放回归解释为什么同类错误不会重复。

Forbidden behavior:
- 只统计错误数量，不追溯原因。
- 为了推进 P1/P2 得分优化而跳过未解释的服务端错误。
- 将服务端错误当成一次性偶发问题，而没有代码、策略、测试或明确拒绝理由。

Implementation owner: `$litchi-replay-analyst -> $litchi-coach -> $litchi-protocol-expert -> $litchi-architect -> $litchi-implementer -> $litchi-tester`

Validation:
- `python -B -m unittest tests.test_replay_watch`
- `python -B tools/quality_gate.py`

Status: done

### 000E. 单轮 AI 复盘文档

Priority: P0

Evidence: 用户要求“要将每轮比赛的回放分析结果单独保存为文档，我要看”。

Expected behavior:
- watcher 为每轮回放生成固定 AI 复盘文档路径：`.replay_watch/analysis_docs/<replay-name>.analysis.md`。
- handoff prompt 明确要求 AI 将最终复盘结论写入该 Markdown 文档，并把路径追加到 process log。
- 机器预分析报告、聊天输出和 process log 不能替代用户可读的单轮 AI 复盘文档。

Forbidden behavior:
- 只把复盘结论发在聊天里。
- 多轮回放共用一个分析文档。
- 只保存机器预分析报告，不保存 AI 补充判断后的最终复盘。

Implementation owner: `$litchi-replay-analyst -> $litchi-coach -> $litchi-tester`

Validation:
- `python -B -m unittest tests.test_replay_watch`
- `python -B tools/quality_gate.py`

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

### 002A. 对抗动作与错误码恢复

Priority: P0/P1

Evidence: 任务书 3.4、4.1、4.2、5.4、6.2、6.3、6.4；通信协议第 11 章错误码和 actions[] 字段矩阵。

Expected behavior:
- 移动中重新检查 `nextNodeId` 的敌方有效设卡和道路障碍；目标被新阻挡时不继续普通 `MOVE`。
- 停靠在节点时，若下一跳被敌方有效设卡阻挡，优先选择合法的攻坚破卡、强制通行或小分队削弱；若只能移动中等待，则提交 `WAIT` 或空动作。
- 每帧最多输出 1 个主车队动作、1 个小分队动作、1 个窗口出牌动作。
- 小分队只在 `NORMAL` 阶段、可用人手足够且目标条件成立时派出：清障、削弱敌方设卡、增援己方设卡、探路高价值路线节点。
- 窗口出牌只针对本队参与且未结束窗口，成本不足时选择 `ABSTAIN`，并尽量避免连续同牌平局。
- 记录并按通信协议错误码恢复策略记忆：移动阻挡、目标无效、资源/任务不可用、窗口冷却、交付/验核失败、急策冲突、强制通行重复等。

Forbidden behavior:
- 主车队已经在 A->B 路线上且 B 被敌方设卡阻挡时，继续发送 `MOVE B`。
- 把 `BREAK_ORDER` 作为独立动作发送。
- 在 RUSH 阶段新派小分队。
- 对未参与的窗口或缺少 `contestId/card` 的窗口出牌。
- 已交付后继续提交主动对抗动作。

Implementation owner: `$litchi-protocol-expert -> $litchi-architect -> $litchi-implementer -> $litchi-tester`

Validation:
- `python -B -m unittest`
- `python -B tools/quality_gate.py`

Status: done

### 002B. 设卡威胁改道与提前规避

Priority: P0/P1

Evidence: 任务书 4.2 规定主车队已在路线边上时，`MOVE` 可以提交当前目标节点，或本段路线起点的其他合法相邻节点改道；用户指出敌方可在我方前进目标点设卡，客户端需要考虑改道和提前规避。

Expected behavior:
- 主车队在 A->B 路线上且 B 出现敌方有效设卡或道路障碍时，优先从 A 的其他合法相邻节点中选择可通往当前战略目标的改道目标。
- 若没有合法改道，再回退到 `WAIT`，并由小分队削弱/清障等副动作处理阻挡。
- 主车队停靠在节点准备出发时，将对手可提前完成设卡的中间节点视为路线风险，优先选择避开风险节点的路径。
- 风险估算只作为路径偏好；如果没有可行替代路径，仍允许走原路线，再依靠破卡、强制通行或小分队处理。

Forbidden behavior:
- 边上遇阻时只等待而不尝试协议允许的改道。
- 移动中把本段起点当作当前位置提交 `BREAK_GUARD` 或 `FORCED_PASS`。
- 为了规避风险选择已经有敌方设卡、道路障碍或不可达的改道目标。

Implementation owner: `$litchi-protocol-expert -> $litchi-architect -> $litchi-implementer -> $litchi-tester`

Validation:
- `python -B -m unittest`
- `python -B tools/quality_gate.py`

Status: done

### 002C. 宫门验核与交付协议细节复核

Priority: P0

Evidence: 任务书 4.5、6.5、7.1；通信协议 `VERIFY_GATE`、`DELIVER`、`VERIFY_GATE_COMPLETE`、`DELIVER_SUCCESS`、`ALREADY_VERIFIED`、`DELIVER_NOT_VERIFIED`。

Expected behavior:
- 只在 `phase=RUSH`、位于 S14、未验核且非忙状态时提交 `VERIFY_GATE`。
- `VERIFY_GATE_COMPLETE`、`VERIFY_GATE_ALREADY_DONE`、`ALREADY_VERIFIED` 应更新本地验核记忆，避免状态字段滞后一帧时重复验核。
- 位于 S15 时，只有已验核、未交付、好果大于 0、鲜度大于 0 时提交 `DELIVER`。
- `DELIVER_SUCCESS`、`ALREADY_DELIVERED` 应更新本地交付记忆，避免交付后主动动作。
- `BREAK_ORDER` 绑定宫门验核时遵守成本规则：坏果足够时可用坏果，否则必须至少留出交付所需好果。

Forbidden behavior:
- 鲜度或好果为 0 时仍提交 `DELIVER`。
- 已收到验核完成/已验核反馈后继续重复 `VERIFY_GATE`。
- 已收到交付成功/已交付反馈后继续提交主动动作。
- 单独发送 `BREAK_ORDER`。

Implementation owner: `$litchi-protocol-expert -> $litchi-architect -> $litchi-implementer -> $litchi-tester`

Validation:
- `python -B -m unittest`
- `python -B tools/quality_gate.py`

Status: done

### 002D. 设卡与反制策略场景完备性验证

Priority: P0/P1

Evidence: 用户担心“设卡和对应策略没有效果”，需要用确定性用例验证设卡收益、反制行为、改道和提前规避是否符合预期。

Expected behavior:
- 己方只在 NORMAL 阶段、可设卡节点、资源留存安全、未超己方有效设卡上限且节点无有效设卡时提交 `SET_GUARD`。
- 主车队移动中或主动等待在路线边上时，若当前目标节点存在敌方有效设卡或道路障碍，只能提交合法改道 `MOVE` 或 `WAIT`，不得提交站点动作。
- 主车队已经停靠在节点且下一跳被敌方设卡或障碍阻挡时，才可优先提交合法 `BREAK_GUARD`、`FORCED_PASS` 或 `CLEAR`，并可配合一条合法小分队动作处理阻挡。
- 路线规划应把对手可提前完成设卡的中间节点视为风险，存在可行替代路径时避开风险节点；无替代路径时仍可走原路线。
- 每帧动作仍满足最多 1 个主车队动作、1 个小分队动作、1 个窗口动作，且不单独发送 `BREAK_ORDER`。

Forbidden behavior:
- 对安全区、已有有效设卡节点、资源不足或已达己方设卡上限时仍提交 `SET_GUARD`。
- 移动中目标已被敌方设卡/障碍阻挡时继续提交 `MOVE` 到该目标。
- `MOVING`/`WAITING` 路线边状态下提交 `BREAK_GUARD`、`FORCED_PASS` 或 `CLEAR`。
- 边上改道选择敌方设卡、道路障碍、不可达节点或本段被阻挡目标。
- 为了验证策略效果而允许非法动作字段、重复主动作或独立 `BREAK_ORDER`。

Implementation owner: `$litchi-protocol-expert -> $litchi-architect -> $litchi-implementer -> $litchi-tester`

Validation:
- `python -B -m unittest tests.test_strategy_baseline`
- `python -B -m unittest`
- `python -B tools/quality_gate.py`

Status: done

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
