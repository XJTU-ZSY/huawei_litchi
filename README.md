# huawei_litchi
西研所软件团体赛

## AI 协作入口

项目级 skills 放在 `.codex/skills/`。开始新一轮开发或复盘时，优先调用 `$litchi-coach`，再由教练按需分派给协议专家、架构师、实现专家、测试专家和回放分析师。

常用命令：

```bash
python -B tools/quality_gate.py
python -B -m unittest
python -B tools/analyze_replay.py <replay-file> --player-id <playerId>
python -B tools/package.py
```

提交代码前优先运行 `python -B tools/quality_gate.py`。如果要把某个回放加入门禁检查：

```bash
python -B tools/quality_gate.py --replay replays/match_001.json --player-id 1001
```
