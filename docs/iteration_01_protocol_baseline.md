# Iteration 01: 协议底座和最低可运行客户端

## 需求卡

Role:

`litchi-implementer`

Requirement:

实现 Python 客户端最小闭环：连接服务器、发送 `registration`、接收 `start`、发送 `ready`、收到每个 `inquire` 后发送同回合 `action`，没有策略动作时发送 `actions: []`，收到 `over` 后退出。

Rule/protocol basis:

- TCP 帧格式：`5 位十进制长度前缀 + UTF-8 JSON body`。
- 消息流程：`registration -> start -> ready -> inquire/action -> over`。
- `action.round` 必须等于刚收到的 `inquire.round`。
- 即使没有主动动作，也发送空动作心跳。
- `start.matchId` 必须原样用于后续 `ready` 和 `action`。

Files likely touched:

```text
litchi_bot/__init__.py
litchi_bot/__main__.py
litchi_bot/client.py
litchi_bot/protocol/framing.py
litchi_bot/protocol/messages.py
litchi_bot/strategy/base.py
litchi_bot/strategy/baseline.py
tests/test_framing.py
tests/test_messages.py
tests/test_client_smoke.py
start.sh
```

Acceptance:

- `encode_frame` 生成 5 位长度前缀，长度按 UTF-8 字节数计算。
- frame decoder 能处理半包、粘包和多个连续消息。
- 客户端启动参数为 `playerId host port`，不写死身份和地址。
- 收到 `start` 后缓存 `matchId` 并发送 `ready.round = start.round`，默认 `1`。
- 收到 `inquire.round = N` 后发送 `action.round = N`。
- 策略异常时发送 `actions: []`，客户端不中断。
- 收到 `over` 后正常退出。
- `python -m unittest discover -s tests` 通过。

Risk:

- 真实服务端字段可能比测试样例多，解析必须允许额外字段。
- 真实 TCP 包可能拆分任意字节，decoder 必须按 bytes 工作，不能先按字符串拆。
- 首版策略为空动作，不能代表可赢，只代表协议可活。

## 架构切片

本轮只实现运行骨架，不实现复杂规则。

```text
socket bytes
  -> protocol.framing.FrameDecoder
  -> JSON message dict
  -> client.Client.handle_message
  -> strategy.BaselineStrategy.decide
  -> protocol.messages.action
  -> protocol.framing.encode_frame
  -> socket bytes
```

错误处理：

- framing 错误：记录日志并断开，避免发送乱码。
- 未知 `msg_name`：忽略并继续等待。
- strategy 抛异常：捕获，发送空动作。
- 缺少 `matchId` 时收到 `inquire`：发送不了合法 action，应记录错误并继续等待下一条消息。

## 测试计划

Unit:

- ASCII JSON frame。
- 中文 JSON frame。
- 半包：前缀分两次到达，body 分多次到达。
- 粘包：两个 frame 一次到达。
- `registration`、`ready`、`action` 消息字段。

Smoke:

- 假服务器接收 registration。
- 假服务器发送 start。
- 客户端回复 ready。
- 假服务器连续发送 3 个 inquire。
- 客户端分别回复 3 个同 round action。
- 假服务器发送 over。
- 客户端退出。

## 明确不做

- 不做路径规划。
- 不做任务、资源、窗口、小分队、天气策略。
- 不做回放解析。
- 不做强规则守门。

这些放到后续迭代，必须建立在本轮协议闭环稳定之后。
