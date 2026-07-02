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
