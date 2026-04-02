# EC2Bot — Telegram AWS 服务器管理机器人

本目录包含可以分享给其他人使用的 Claude Code Skills 和开源项目。

---

## ec2bot-open — EC2Bot 开源项目

```
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
```
ec2bot-open/
├── README.md                          # 完整文档（快速部署 + 命令速查 + 架构说明）
├── .gitignore                         # Git 忽略规则
├── config/
│   ├── config.yaml.example            # 配置模板
│   └── .env.example                   # 环境变量模板
├── deploy/
│   ├── Dockerfile                     # Docker 镜像
│   ├── docker-compose.yml             # Docker 一键部署
│   └── ec2bot.service                 # systemd 服务文件
├── app/                               # ← 从 ec2bot/ 目录复制源码
│   ├── ec2_bot.py                     # 主程序
│   ├── aws_manager_secure.py          # AWS API 封装
│   ├── monitor_secure.py              # 后台监控引擎
│   ├── sync_instances.py              # 实例自动同步
│   ├── config_manager.py              # 配置管理
│   ├── audit_store.py                 # 审计日志
│   ├── state_store.py                 # 状态缓存
│   ├── secret_manager.py              # 凭证管理
│   └── requirements.txt               # Python 依赖
└── skills/
    ├── ec2bot-deploy/SKILL.md         # 配套 Skill：一键部署
    └── ec2bot-account/SKILL.md        # 配套 Skill：添加 AWS 账户
```

**核心能力：** 多账户管理 | 宕机告警 | 远程重启 | IP 搜索 | 三级权限 | 生产保护 | 审计日志

**部署方式：** 直接运行 / Docker / systemd（详见 README.md）

> 注意：发布前需将 ec2bot/ 源码复制到 ec2bot-open/app/ 目录。

---

## shared-skills/ — 通用 Claude Code Skills

无基础设施绑定，任何人拿走就能用的 Skills。

```
shared-skills/
├── make-plan/SKILL.md       # 分阶段实施规划（零依赖，纯方法论）
├── do/SKILL.md              # 分阶段计划执行（搭配 make-plan）
├── fix-monitoring/SKILL.md  # Prometheus 监控修复（通用 Prometheus 环境）
├── server-check/SKILL.md    # 批量服务器巡检（通用 Linux SSH）
├── add-user/SKILL.md        # 批量添加 Linux 用户（通用 Linux SSH）
└── create-ec2/SKILL.md      # 创建 EC2 实例（通用 AWS 环境）
```

### 安装方式

将 SKILL.md 文件复制到 Claude Code 的 skills 目录：

```bash
# 安装单个 Skill
mkdir -p .claude/skills/make-plan
cp shared-skills/make-plan/SKILL.md .claude/skills/make-plan/

# 或批量安装
for skill in make-plan do fix-monitoring server-check add-user create-ec2; do
  mkdir -p .claude/skills/$skill
  cp shared-skills/$skill/SKILL.md .claude/skills/$skill/
done
```

### Skills 速查

| Skill | 命令 | 依赖 | 适用人群 |
|-------|------|------|---------|
| 分阶段规划 | `/make-plan` | 无 | 所有 Claude Code 用户 |
| 分阶段执行 | `/do` | 无 | 所有 Claude Code 用户 |
| 监控修复 | `/fix-monitoring` | Prometheus + SSH | Prometheus 运维 |
| 服务器巡检 | `/server-check` | SSH | Linux 运维 |
| 批量加用户 | `/add-user` | SSH + sudo | Linux 运维 |
| 创建 EC2 | `/create-ec2` | AWS CLI | AWS 用户 |
