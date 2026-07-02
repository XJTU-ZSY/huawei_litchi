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
- `.replay_watch/process_logs/`：每一轮从回放分析、需求卡、实现、测试到提交的过程日志

你可以把 `.replay_watch/ai_tasks/*.prompt.md` 的内容交给 opencode/Codex，让 AI 按项目 skills 做深度分析和需求卡。

若希望把脚本生成的初步需求卡直接追加到 `docs/backlog.md`：

```bash
python -B tools/watch_replays.py replays --player-id 1001 --append-backlog
```

如果要让 watcher 在生成 prompt 后自动调用 AI，推荐使用项目内 wrapper：

```bash
python -B tools/watch_replays.py replays --player-id 1001 --ai-command-template "python -B tools/run_ai_task.py --prompt-file {task}" --auto-implement
```

不加 `--auto-implement` 时，AI 只做回放分析、教练排序和需求卡，不会改代码。

当 `--ai-command-template` 成功返回后，watcher 会扫描回放目录中最新的 `*.manifest.json`，读取 `clientA.doneFile` / `clientB.doneFile`，并在回放目录创建对应 doneFile 标记。只标记单侧时可加：

```bash
python -B tools/watch_replays.py replays --player-id 1001 --ai-command-template "python -B tools/run_ai_task.py --prompt-file {task}" --auto-implement --done-client clientA
```

本地调试如果没有 manifest，可加 `--skip-done-file`。

手动优化完代码后，也可以单独创建 doneFile：

```bash
python -B tools/mark_replay_done.py replays --client clientA
```

手动追加过程日志：

```bash
python -B tools/process_log.py .replay_watch/process_logs/match_001.process.md --stage "Implementation" --message "Implemented task selector and ran quality gate."
```
