# Iteration 02: 状态解析、图结构和保守交付策略

## 需求卡

Role:

`litchi-implementer`

Requirement:

在第一轮协议闭环基础上，实现最小内部状态、地图图结构和保守交付策略。客户端应能从 `start.edges[]` 建图，从 `inquire.players[]` 找到本方状态，从 `inquire.nodes[]` 读取当前节点公开处理信息，并在安全条件下输出 `PROCESS`、`VERIFY_GATE`、`DELIVER` 或下一跳 `MOVE`。

Rule/protocol basis:

- `start.players[]` 用于识别本方 `playerId/teamId`。
- `start.nodes[]`、`start.edges[]`、`start.map.gameplay.roles` 提供本局地图、宫门和终点。
- `start.map.gameplay.processNodes[]` 或每帧 `inquire.nodes[].processType/processRound` 用于识别固定处理点。
- `inquire.players[]` 提供 `state/currentNodeId/nextNodeId/verified/delivered/goodFruit/freshness/currentProcess`。
- 移动只能发往合法相邻节点，路线单向时必须符合 `fromNodeId -> toNodeId`。
- 固定处理站点离站前应先 `PROCESS`；宫门验核点应发 `VERIFY_GATE`。
- `VERIFY_GATE` 只能在 `phase = RUSH` 且本方位于宫门、未验核、非读条状态时提交。
- `DELIVER` 需要位于终点、已验核、未交付、好果和鲜度都大于 0，且不处于移动/处理/验核等阻塞状态。

Files likely touched:

```text
litchi_bot/core/__init__.py
litchi_bot/core/models.py
litchi_bot/core/game_state.py
litchi_bot/core/graph.py
litchi_bot/strategy/baseline.py
tests/test_graph.py
tests/test_game_state.py
tests/test_baseline_strategy.py
```

Acceptance:

- 能从 `start` 中缓存 roles、nodes、edges、processNodes 和本方 player 信息。
- 图结构支持单向和双向边，返回从当前节点到目标节点的下一跳。
- 策略在 `PROCESSING/VERIFYING/FORCED_PASSING/RESTING/CONTESTING` 等阻塞状态返回空动作。
- 本方已交付时返回空动作。
- 位于 S15 且满足交付条件时返回 `DELIVER`。
- 位于 S14、`phase=RUSH`、未验核时返回 `VERIFY_GATE`。
- 位于需要普通固定处理的节点时返回 `PROCESS`，不对 `VERIFY` 节点发 `PROCESS`。
- 普通节点按最短路径返回 `MOVE targetNodeId=<下一跳>`。
- `python -m unittest discover -s tests` 通过。

Risk:

- 本轮不处理道路障碍、敌方设卡、窗口争夺和任务/资源绕路，真实对战中可能被阻挡或错过收益。
- 处理完成状态在协议中主要由服务端状态体现；本轮只避免在读条中重复发动作，不建立“离站前处理已完成”的长期记忆。
- 首版路径权重只使用 `distance`，不做天气、鲜度和资源收益权重。

## 明确不做

- 不做任务选择。
- 不做资源领取和使用。
- 不做窗口出牌。
- 不做障碍清理、强制通行、设卡或攻坚。
- 不做小分队。

这些内容由后续回放和策略需求驱动。
