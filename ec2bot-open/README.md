# EC2Bot — Telegram 管理你的 AWS 服务器

手机上随时查状态、收告警、重启机器。不用打开电脑，不用登录 AWS 控制台。

## 解决什么问题

- 半夜服务器挂了 → Telegram 秒级告警推送到手机
- 外出时需要重启机器 → Telegram 发条命令就能操作
- 多个 AWS 账户几百台机器 → 一个 Bot 统一管理
- 谁动了服务器 → 审计日志自动记录

## 核心能力

| 能力 | 说明 |
|------|------|
| 多账户管理 | 一个 Bot 管理 N 个 AWS 账户，跨区域（新加坡/香港/首尔/...） |
| 实时监控 | 每 2 分钟轮询，宕机/恢复/CPU 异常自动推送告警 |
| 远程控制 | 查询 / 重启 / 启动 / 停止，双重确认防误操作 |
| IP 搜索 | 输入一个 IP，秒查是哪个账户的哪台机器 |
| 权限分级 | admin / operator / viewer 三级 RBAC |
| 生产保护 | 关键实例禁止停机、工作时间段保护、操作冷却 |
| 审计日志 | SQLite 持久化：谁、什么时候、对哪台机器、做了什么 |
| 自动发现 | `/account_import` 一键扫描 AWS 导入所有实例 |
| 轻量部署 | 3 个 pip 依赖，5 分钟跑起来 |

## 告警效果

```
[状态变化告警]
────────────────────────────
账户  : 生产环境 (Prod)
实例  : web-server-01
ID    : i-0bf15d6d8ec0065e9
变化  : [ ON  ]  =>  [ OFF ]
时间  : 2026-03-20 11:23 CST
  !! 实例意外停止，请检查 !!
```

```
[CPU 告警]
────────────────────────────
账户  : 生产环境 (Prod)
实例  : app-server-03
CPU   : 92.1%  [##################--]
阈值  : 85%
连续  : 2 次超阈值
```

## 实例详情

```
[ ON  ] web-server-01
──────────────────────────────
实例ID   : i-0320626a45b7bd57e
公网IP   : 54.169.xxx.xxx
内网IP   : 172.31.22.10
规格     : c5.2xlarge
运行时长 : 12天5小时
日费用   : $9.216 (按需价估算)

性能指标 (近1小时)
──────────────────────────────
CPU 趋势 : ._-~+=*#  87.3%
CPU 均值 : 43.2%    峰值 : 87.3%
网络流入 : 128.45 MB
网络流出 : 56.32 MB
```

---

## 快速部署

### 前提条件

1. **Telegram Bot Token** — 找 [@BotFather](https://t.me/BotFather) 创建机器人，拿到 Token
2. **AWS Access Key** — IAM 用户需要以下权限：
   ```json
   {
     "Effect": "Allow",
     "Action": [
       "ec2:DescribeInstances",
       "ec2:DescribeInstanceStatus",
       "ec2:RebootInstances",
       "ec2:StartInstances",
       "ec2:StopInstances",
       "cloudwatch:GetMetricStatistics",
       "cloudwatch:ListMetrics"
     ],
     "Resource": "*"
   }
   ```
3. **Python 3.9+**
4. **你的 Telegram 用户 ID** — 找 [@userinfobot](https://t.me/userinfobot) 获取

### 方式一：直接运行（5 分钟）

```bash
# 1. 克隆仓库
git clone https://github.com/yourname/ec2bot.git
cd ec2bot

# 2. 安装依赖
pip3 install -r app/requirements.txt

# 3. 复制配置模板
cp config/config.yaml.example config/config.yaml
cp config/.env.example config/.env

# 4. 编辑 .env，填入 Token 和 AWS 凭证
vi config/.env

# 5. 编辑 config.yaml，填入你的 Telegram 用户 ID
vi config/config.yaml

# 6. 启动
cd app && python3 ec2_bot.py
```

### 方式二：Docker 部署（推荐生产环境）

```bash
# 1. 克隆仓库
git clone https://github.com/yourname/ec2bot.git
cd ec2bot

# 2. 复制配置模板并编辑
cp config/config.yaml.example config/config.yaml
cp config/.env.example config/.env
vi config/.env
vi config/config.yaml

# 3. 一键启动
docker-compose up -d

# 4. 查看日志
docker-compose logs -f
```

### 方式三：systemd 服务（Linux 服务器）

```bash
# 1. 部署文件到 /opt/ec2bot/
sudo mkdir -p /opt/ec2bot/{app,config,logs,run}
sudo cp app/*.py /opt/ec2bot/app/
sudo cp app/requirements.txt /opt/ec2bot/app/
sudo cp config/config.yaml.example /opt/ec2bot/config/config.yaml
sudo cp config/.env.example /opt/ec2bot/config/.env

# 2. 安装依赖
cd /opt/ec2bot && python3 -m venv venv
source venv/bin/activate
pip install -r app/requirements.txt

# 3. 编辑配置
vi /opt/ec2bot/config/.env
vi /opt/ec2bot/config/config.yaml

# 4. 安装 systemd 服务
sudo cp deploy/ec2bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ec2bot
sudo systemctl start ec2bot

# 5. 验证
sudo systemctl status ec2bot
```

---

## 命令速查表

### 所有用户

| 命令 | 说明 |
|------|------|
| `/start` `/help` | 显示所有命令 |
| `/whoami` | 查看自己的用户 ID 和角色 |
| `/dashboard` | 全局仪表盘（所有账户实例概览） |
| `/status` | 选定账户的实例状态（分页） |
| `/check` | 一键全量巡检，输出异常列表 |
| `/searchip <IP>` | 按 IP 搜索实例（支持公网/内网） |
| `/searchhost <关键字>` | 按主机名搜索实例 |
| `/log` | 查看最近 20 条操作日志 |
| `/audit` | 查看自己的操作日志 |

### 操作员 (operator+)

| 命令 | 说明 |
|------|------|
| `/control` | 进入控制模式（重启/启动/停止） |

### 管理员 (admin)

| 命令 | 说明 |
|------|------|
| `/account_list` | 列出所有 AWS 账户 |
| `/account_show <别名>` | 查看账户详情 |
| `/account_add <别名>` | 添加新 AWS 账户（引导式） |
| `/account_delete <别名>` | 删除 AWS 账户 |
| `/account_import <别名>` | 自动扫描并导入 AWS 实例 |
| `/account_reload` | 重新加载配置文件 |
| `/instance_add <别名>` | 添加实例到账户 |
| `/instance_delete <别名> <ID>` | 从账户删除实例 |
| `/secret_add <前缀>` | 录入 AWS 凭证（私聊） |
| `/secret_status <前缀>` | 检查凭证是否存在 |
| `/cpualarm` | 开关 CPU 告警 |

### 快捷用法

```
ip 10.0.0.1        → 等同于 /searchip 10.0.0.1
host web-server     → 等同于 /searchhost web-server
查IP 10.0.0.1      → 中文快捷搜索
查主机 web          → 中文快捷搜索
```

---

## 架构概览

```
┌─────────────┐     Telegram API     ┌──────────────────┐
│  Telegram   │◄──────────────────►  │   ec2_bot.py     │
│  用户/群组   │                      │  (主程序 + 路由)   │
└─────────────┘                      └───────┬──────────┘
                                             │
                    ┌────────────────────────┼────────────────────┐
                    │                        │                    │
             ┌──────▼──────┐    ┌───────────▼─────┐    ┌───────▼────────┐
             │ aws_manager │    │ monitor_secure  │    │  config_manager │
             │ (AWS API)   │    │ (后台监控引擎)   │    │  (YAML 配置)    │
             └──────┬──────┘    └───────┬─────────┘    └────────────────┘
                    │                   │
              ┌─────▼─────┐     ┌──────▼──────┐
              │   boto3   │     │ state_store  │
              │ (AWS SDK) │     │ (SQLite 缓存) │
              └───────────┘     └─────────────┘
                                       │
                                ┌──────▼──────┐
                                │ audit_store  │
                                │ (操作审计)    │
                                └─────────────┘
```

### 模块说明

| 模块 | 文件 | 职责 |
|------|------|------|
| 主程序 | `ec2_bot.py` | Telegram 命令路由、权限校验、UI 构建 |
| AWS 封装 | `aws_manager_secure.py` | boto3 会话管理、实例查询/控制、CloudWatch |
| 监控引擎 | `monitor_secure.py` | 后台轮询、状态变化检测、CPU 告警、冷却防刷 |
| 实例同步 | `sync_instances.py` | 自动发现 AWS 实例、同步到配置（可 cron） |
| 配置管理 | `config_manager.py` | YAML 配置读写、账户/实例增删 |
| 审计日志 | `audit_store.py` | SQLite 操作记录 |
| 状态缓存 | `state_store.py` | SQLite 实例状态持久化 |
| 凭证管理 | `secret_manager.py` | .env 文件凭证读写 |

---

## 安全策略

### 权限体系 (RBAC)

```yaml
telegram:
  admins: [123456789]       # 完全控制权
  operators: [987654321]    # 可操作实例（重启/启动/停止）
  viewers: [111222333]      # 只读（查状态/搜索/看日志）
```

- 群组 ID（负数）可加入 viewers，群内所有人获得只读权限
- 凭证录入仅限私聊，防止在群聊中泄露

### 生产保护

```yaml
policy:
  protect_stop_in_production: true        # 禁止停止生产环境关键实例
  require_double_confirm_for_stop: true   # 停止操作需二次确认
  operation_cooldown_seconds: 300         # 操作冷却 5 分钟
  business_hours_protect:                 # 工作时间段保护
    enabled: true
    range: "09:00-22:00"
```

### 实例级权限

每个实例可独立配置允许的操作：

```yaml
instances:
  - id: i-0320626a45b7bd57e
    name: production-db
    critical: true                   # 标记为关键实例
    allow_actions: [status, detail]  # 只允许查看，禁止任何控制操作
```

---

## 监控参数调优

```yaml
monitor:
  check_interval: 120           # 轮询间隔（秒），越小越及时，API 调用越多
  cpu_alert_threshold: 85       # CPU 告警阈值（%）
  alert_consecutive: 2          # 连续 N 次超阈值才告警（防毛刺误报）
  alert_cooldown: 600           # 同一告警冷却时间（秒），防重复推送
  notify_state_change: true     # 推送状态变化（running↔stopped）
  enable_recovery_notice: true  # 推送恢复通知（stopped→running）
  enable_cpu_alarm: false       # CPU 告警总开关（可通过 /cpualarm 切换）
  cloudwatch_period: 300        # CloudWatch 数据粒度（秒）
  timezone: Asia/Shanghai       # 本地时区
```

---

## 自动同步实例

`sync_instances.py` 可独立运行或配置 cron，自动发现 AWS 新增/终止的实例：

```bash
# 手动执行
python3 sync_instances.py

# 仅预览，不修改
python3 sync_instances.py --dry-run

# 仅同步指定账户
python3 sync_instances.py --account "生产环境"

# 配置 cron（每 2 小时同步）
crontab -e
0 */2 * * * cd /opt/ec2bot && /opt/ec2bot/venv/bin/python3 app/sync_instances.py >> logs/sync.log 2>&1
```

同步完成后会自动通过 Telegram 推送变更报告。

---

## 依赖

```
python-telegram-bot>=20.0    # Telegram Bot API
boto3>=1.26.0                # AWS SDK
pyyaml>=6.0                  # YAML 配置解析
```

仅 3 个第三方依赖，其余全部使用 Python 标准库。

---

## License

MIT
