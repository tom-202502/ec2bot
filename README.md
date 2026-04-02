# EC2Bot — Telegram AWS 服务器管理机器人

通过 Telegram 随时随地管理 AWS EC2 服务器。半夜宕机手机秒收告警，外出时一条命令远程重启，不用打开电脑登 AWS 控制台。

## 解决什么问题

- 服务器挂了没人知道 → Telegram 秒级推送告警（宕机/恢复/CPU 异常）
- 外出或深夜需要操作服务器 → Telegram 发命令直接重启/启动/停止
- 多个 AWS 账户、几百台机器分散管理 → 一个 Bot 统一管理
- 谁动了生产机器 → 审计日志自动记录（谁、什么时候、对哪台、做了什么）

## 核心能力

| 能力 | 说明 |
|------|------|
| 多账户管理 | 一个 Bot 管理 N 个 AWS 账户，跨区域 |
| 实时监控 | 每 2 分钟轮询，宕机/恢复/CPU 异常自动推送告警 |
| 远程控制 | 重启/启动/停止，双重确认防误操作 |
| IP 搜索 | 输入一个 IP，秒查是哪个账户的哪台机器 |
| 权限分级 | admin/operator/viewer 三级 RBAC |
| 生产保护 | 关键实例禁停、工作时间保护、操作冷却 |
| 审计日志 | SQLite 持久化：所有操作可追溯 |
| 自动发现 | /account_import 一键扫描 AWS 导入全部实例 |
| 轻量部署 | 3 个 pip 依赖，5 分钟跑起来 |

## 告警效果

状态变化告警：
实例 web-server-01 状态从 [ON] 变为 [OFF]，推送"实例意外停止，请检查"

CPU 告警：
实例 app-server-03 CPU 92.1% 超过阈值 85%，连续 2 次超标

## 命令一览

所有用户：/dashboard（全局仪表盘）、/status（账户状态）、/check（一键巡检）、/searchip（IP搜索）、/searchhost（主机名搜索）、/log（操作日志）

操作员：/control（远程控制：重启/启动/停止）

管理员：/account_add（添加账户）、/account_import（自动导入实例）、/secret_add（录入凭证）、/cpualarm（开关CPU告警）等

## 技术栈

- 语言：Python 3
- 依赖：python-telegram-bot + boto3 + pyyaml（仅 3 个）
- 存储：SQLite（审计日志 + 状态缓存）
- 部署：直接运行 / Docker / systemd

## 部署方式

1. 克隆仓库 → 2. pip install → 3. 填 .env（Bot Token + AWS Key）→ 4. 填 config.yaml（用户ID）→ 5. 启动
```

**适用场景：** `网络通信` `安全加固`

**开发语言：** Python

**开源协议：** MIT

**主要贡献者：** 曹睿

**协作者：** （空）

**Git 仓库地址：** [https://github.com/yourname/ec2bot](https://github.com/tom-202502/ec2bot)
