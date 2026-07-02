# 协议速记

## TCP 帧

```text
5 位十进制长度前缀 + UTF-8 JSON body
```

长度是 JSON body 的 UTF-8 字节数，不是字符数。客户端必须按字节缓存，支持半包、粘包和中文跨包。

## 主流程

```text
registration
  <- start
ready
  <- inquire(round=N)
action(round=N)
  <- inquire(round=N+1, events/actionResults)
  <- over
```

## 每帧 action

必须包含：

```json
{
  "msg_name": "action",
  "msg_data": {
    "matchId": "...",
    "round": 1,
    "playerId": 1001,
    "actions": []
  }
}
```

没有动作时也发送 `actions: []`。

## 动作上限

每帧最多：
- 主车队动作 1 个
- 小分队动作 1 个
- 窗口出牌动作 1 个
- 终局急策动作 1 个

`BREAK_ORDER` 不作为独立动作发送，只能作为 `rushTactic` 绑定在 `BREAK_GUARD` 或 `VERIFY_GATE` 上。

## 结果判断

不要只看 `actionResults.accepted=true`。必须结合：
- `events[]`
- `actionResults[]`
- 下一帧 `players[]` / `nodes[]` / `tasks[]`

协议级错误看 `msg_name=error`；业务拒绝通常在下一帧事件里。
