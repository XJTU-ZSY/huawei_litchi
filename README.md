# huawei_litchi
西研所软件团体赛

## AI 协作入口

项目级 skills 放在 `.codex/skills/`。开始新一轮开发或复盘时，优先调用 `$litchi-coach`，再由教练按需分派给协议专家、架构师、实现专家、测试专家和回放分析师。

常用命令：

```bash
python -B tools/quality_gate.py
python -B tools/watch_replays.py replays --player-id <playerId>
python -B -m unittest
python -B tools/analyze_replay.py <replay-file> --player-id <playerId>
python -B tools/package.py
```

提交代码前优先运行 `python -B tools/quality_gate.py`。如果要把某个回放加入门禁检查：

```bash
python -B tools/quality_gate.py --replay replays/match_001.json --player-id 1001
```

持续监控回放目录：

```bash
python -B tools/watch_replays.py replays --player-id 1001
```

默认会生成两类文件：

- `.replay_watch/reports/`：机器预分析报告
- `.replay_watch/ai_tasks/`：给 `$litchi-replay-analyst` 和 `$litchi-coach` 使用的 AI handoff prompt

你可以把 `.replay_watch/ai_tasks/*.prompt.md` 的内容交给 opencode/Codex，让 AI 按项目 skills 做深度分析和需求卡。

若希望把脚本生成的初步需求卡直接追加到 `docs/backlog.md`：

```bash
python -B tools/watch_replays.py replays --player-id 1001 --append-backlog
```

如果你的 opencode 有命令行入口，可以让 watcher 在生成 prompt 后自动调用它：

```bash
python -B tools/watch_replays.py replays --player-id 1001 --ai-command-template "opencode run --prompt-file {task}"
```
