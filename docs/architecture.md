# 架构说明

## 模块

```text
litchi_bot/
  main.py              启动入口
  client.py            TCP 客户端循环
  framing.py           5 位长度前缀拆包/组包
  protocol.py          registration/ready/action 消息构造
  game_state.py        start/inquire 状态归一化
  graph.py             地图图和最短路
  decision.py          每帧安全决策器
  replay.py            回放解析与报告
  strategy/
    baseline.py        P0 策略
    contest.py         窗口出牌
tools/
  analyze_replay.py    离线复盘入口
tests/
  单元测试
```

## 数据流

```text
socket bytes
  -> FrameDecoder
  -> JSON message
  -> GameMemory
  -> GameSnapshot
  -> BaselineDecisionEngine
  -> protocol.action()
  -> encode_frame()
  -> socket bytes
```

## 原则

- 协议层不写策略。
- 策略层不碰 socket。
- 状态层保留原始字典，未建模字段不丢。
- 决策输出始终是 JSON-compatible action dict。
- 决策异常时回退为空动作。
