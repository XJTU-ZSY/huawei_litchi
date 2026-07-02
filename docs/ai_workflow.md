# AI 协作工作流

本项目用角色化 skill 组织 AI 写代码。每轮不要直接“让 AI 随便优化”，而是先由教练把问题变成可验收的需求卡，再交给协议、架构、实现和测试角色处理。

项目级 skills 放在 `.codex/skills/`，这是本仓库内给 Codex/opencode 识别和随代码一起提交的位置。顶层不再保留单独的 `skills/` 目录。

## 角色

| 角色 | 使用场景 | 产物 |
|---|---|---|
| `$litchi-coach` | 排优先级、制定迭代目标、处理复盘结论 | 需求卡、backlog 更新 |
| `$litchi-protocol-expert` | 协议字段、动作合法性、错误码、事件解释 | 协议约束和测试点 |
| `$litchi-architect` | 模块边界、状态设计、接口变更 | 架构方案和影响范围 |
| `$litchi-implementer` | 按需求卡写代码 | 小范围代码变更 |
| `$litchi-tester` | 单测、mock、回放回归、打包检查 | 测试报告 |
| `$litchi-replay-analyst` | 比赛回放分析、学习对手策略 | 复盘报告和新需求卡 |

## 迭代流程

```text
用户/回放输入
  -> 教练分类 P0/P1/P2
  -> 协议专家确认规则和字段
  -> 架构师确定模块与接口
  -> 实现专家改代码
  -> 测试专家验证
  -> 教练验收并更新 backlog
```

## 需求卡模板

```text
Title:
Priority:
Evidence:
Expected behavior:
Forbidden behavior:
Implementation owner:
Validation:
Status:
```

## 当前优先级

P0 是比赛存活线：不掉线、每帧有 action 包、动作不冲突、能完成 S14 验核和 S15 交付。

P1 是得分线：普通皇榜任务基础分尽量达到 90，合理拿资源，按时进入宫宴冲刺。

P2 是对抗线：窗口出牌、设卡/破卡、强制通行、从对手回放学习策略。

## 质量门禁

每次代码变更后、提交前运行：

```bash
python -B tools/quality_gate.py
```

门禁会检查：

- `start.sh` 是否保留比赛要求的 3 个参数入口。
- 单元测试是否全部通过。
- 参赛 ZIP 是否能生成。
- ZIP 根目录是否直接包含 `start.sh`。
- ZIP 是否只包含比赛运行需要的 `start.sh` 和 `litchi_bot/`，不包含测试、文档、skills、缓存或字节码。

如果要把回放纳入回归：

```bash
python -B tools/quality_gate.py --replay replays/match_001.json --player-id 1001
```

默认要求被检查玩家的 `ACTION_REJECTED` 和 `INVALID_ACTION` 都为 0。必要时可用 `--max-rejected` 和 `--max-invalid` 为特定回放设置阈值。

## 回放目录监控

长期监控某个回放目录：

```bash
python -B tools/watch_replays.py replays --player-id 1001
```

流程：

1. watcher 轮询目录中的 `.json/.jsonl/.log/.txt/.replay` 文件。
2. 等文件稳定后生成机器预分析报告。
3. 同时生成 `.replay_watch/ai_tasks/*.prompt.md`，该 prompt 明确要求使用 `$litchi-replay-analyst` 和 `$litchi-coach`。
4. 将 prompt 交给 opencode/Codex 后，由 AI 读取原始回放和机器报告，补充策略判断并生成需求卡。
5. 默认报告写入 `.replay_watch/reports/`，AI handoff prompt 写入 `.replay_watch/ai_tasks/`，处理状态写入 `.replay_watch/state.json`。
6. 加 `--append-backlog` 时，脚本会将机器生成的初步需求卡追加到 `docs/backlog.md`；更推荐先让 AI 审核 prompt 后再写入 backlog。

测试或手动批处理时只扫描一次：

```bash
python -B tools/watch_replays.py replays --player-id 1001 --once
```

如果 opencode 支持命令行 prompt 文件，可以使用：

```bash
python -B tools/watch_replays.py replays --player-id 1001 --ai-command-template "opencode run --prompt-file {task}"
```

`--ai-command-template` 支持 `{task}`、`{replay}`、`{report}` 占位符。具体命令取决于本机 opencode CLI。
