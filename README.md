# EC2Bot — Telegram AWS 服务器管理机器人

本目录包含 EC2Bot 开源项目和配套的 Claude Code Skills。

> **快速导航**
>
> - [ec2bot-open](#ec2bot-open--开源项目) — 完整的开源项目（含部署文档）
> - [shared-skills](#shared-skills--通用-claude-code-skills) — 通用 Claude Code Skills 合集

---

## ec2bot-open — 开源项目

通过 Telegram 随时随地管理 AWS EC2 服务器。半夜宕机手机秒收告警，外出时一条命令远程重启，不用打开电脑登 AWS 控制台。

### 解决什么问题

| 痛点 | EC2Bot 方案 |
|------|------------|
| 服务器挂了没人知道 | Telegram 秒级推送告警（宕机/恢复/CPU 异常） |
| 外出或深夜需要操作服务器 | Telegram 发命令直接重启/启动/停止 |
| 多个 AWS 账户、几百台机器分散管理 | 一个 Bot 统一管理 |
| 谁动了生产机器 | 审计日志自动记录（谁、什么时候、对哪台、做了什么） |

### 核心能力

| 能力 | 说明 |
|------|------|
| **多账户管理** | 一个 Bot 管理 N 个 AWS 账户，跨区域 |
| **实时监控** | 每 2 分钟轮询，宕机/恢复/CPU 异常自动推送告警 |
| **远程控制** | 重启/启动/停止，双重确认防误操作 |
| **IP 搜索** | 输入一个 IP，秒查是哪个账户的哪台机器 |
| **权限分级** | admin / operator / viewer 三级 RBAC |
| **生产保护** | 关键实例禁停、工作时间保护、操作冷却 |
| **审计日志** | SQLite 持久化：所有操作可追溯 |
| **自动发现** | `/account_import` 一键扫描 AWS 导入全部实例 |
| **轻量部署** | 3 个 pip 依赖，5 分钟跑起来 |

### 告警效果

**状态变化告警：**

```
[状态变化告警]
────────────────────────────
账户  : 生产环境 (Prod)
实例  : web-server-01
变化  : [ ON  ]  =>  [ OFF ]
时间  : 2026-03-20 11:23 CST
  !! 实例意外停止，请检查 !!
```

**CPU 告警：**

```
[CPU 告警]
────────────────────────────
账户  : 生产环境 (Prod)
实例  : app-server-03
CPU   : 92.1%  [##################--]
阈值  : 85%
连续  : 2 次超阈值
```

### 命令一览

#### 所有用户

| 命令 | 说明 |
|------|------|
| `/dashboard` | 全局仪表盘（所有账户实例概览） |
| `/status` | 选定账户的实例状态 |
| `/check` | 一键全量巡检，输出异常列表 |
| `/searchip <IP>` | 按 IP 搜索实例（公网/内网） |
| `/searchhost <关键字>` | 按主机名搜索实例 |
| `/log` | 查看最近操作日志 |

#### 操作员 (operator+)

| 命令 | 说明 |
|------|------|
| `/control` | 远程控制（重启/启动/停止） |

#### 管理员 (admin)

| 命令 | 说明 |
|------|------|
| `/account_add <别名>` | 添加新 AWS 账户 |
| `/account_import <别名>` | 自动扫描并导入 AWS 实例 |
| `/secret_add <前缀>` | 录入 AWS 凭证（限私聊） |
| `/cpualarm` | 开关 CPU 告警 |

### 技术栈

| 组件 | 选型 |
|------|------|
| 语言 | Python 3 |
| 依赖 | `python-telegram-bot` + `boto3` + `pyyaml`（仅 3 个） |
| 存储 | SQLite（审计日志 + 状态缓存） |
| 部署 | 直接运行 / Docker / systemd |

### 快速部署

```bash
git clone → pip install → 填 .env（Bot Token + AWS Key）→ 填 config.yaml（用户 ID）→ 启动
```

详见 [ec2bot-open/README.md](ec2bot-open/README.md)

### 目录结构

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

> **注意：** 发布前需将 `ec2bot/` 源码复制到 `ec2bot-open/app/` 目录。

---

## shared-skills — 通用 Claude Code Skills

无基础设施绑定，任何人拿走就能用的 Skills。

### 目录结构

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

# 批量安装
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
