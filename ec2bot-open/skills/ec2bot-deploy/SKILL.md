---
name: ec2bot-deploy
description: 一键部署 EC2Bot 到 Linux 服务器。当用户提到"部署 ec2bot""安装 ec2bot""搭建监控机器人"时使用。
---

# 部署 EC2Bot

将 EC2Bot 部署到一台 Linux 服务器上，完成从安装到运行的全流程。

## 触发词
用户提到"部署 ec2bot""安装 ec2bot""搭建监控机器人""装 bot"时触发。

## 参数
- `$ARGUMENTS`：目标服务器信息（可选），如 `/ec2bot-deploy ubuntu@1.2.3.4`
- 无参数时部署到本机

## 前提条件
- 目标服务器：Python 3.9+、pip、SSH 可达
- 用户准备好：Telegram Bot Token、AWS Access Key/Secret Key、Telegram 用户 ID

## 执行流程

### 1. 检查环境
```bash
python3 --version
pip3 --version
```
如果 Python < 3.9，提示升级。

### 2. 创建部署目录
```bash
sudo mkdir -p /opt/ec2bot/{app,config,logs,run}
```

### 3. 上传代码
```bash
# 如果本地有代码
scp -o StrictHostKeyChecking=no app/*.py <目标>:/opt/ec2bot/app/
scp -o StrictHostKeyChecking=no app/requirements.txt <目标>:/opt/ec2bot/app/
```

### 4. 安装依赖
```bash
cd /opt/ec2bot
python3 -m venv venv
source venv/bin/activate
pip install -r app/requirements.txt
```

### 5. 引导配置
询问用户以下信息并生成配置文件：

**必填项：**
- Telegram Bot Token（从 @BotFather 获取）
- AWS Access Key ID
- AWS Secret Access Key
- AWS 区域（如 ap-southeast-1）
- 管理员 Telegram 用户 ID（从 @userinfobot 获取）

**可选项（有默认值）：**
- 监控间隔（默认 120 秒）
- CPU 告警阈值（默认 85%）
- 时区（默认 Asia/Shanghai）

根据用户输入生成 `/opt/ec2bot/config/.env` 和 `/opt/ec2bot/config/config.yaml`。

### 6. 前台测试
```bash
cd /opt/ec2bot/app && /opt/ec2bot/venv/bin/python3 ec2_bot.py
```
观察输出，确认出现 "Bot 启动" + "巡检引擎启动" 日志。
让用户在 Telegram 中发送 `/start` 验证机器人响应。

### 7. 安装 systemd 服务
```bash
sudo cp deploy/ec2bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ec2bot
sudo systemctl start ec2bot
```

### 8. 验证
```bash
sudo systemctl status ec2bot --no-pager
```

### 9. 自动导入实例
提示用户在 Telegram 中执行：
```
/account_import 我的AWS账户
```
Bot 会自动扫描 AWS 并导入所有 EC2 实例。

### 10. 配置自动同步（可选）
```bash
crontab -e
# 添加：每 2 小时自动同步实例
0 */2 * * * cd /opt/ec2bot && /opt/ec2bot/venv/bin/python3 app/sync_instances.py >> logs/sync.log 2>&1
```

## 输出
部署完成后汇总：
- Bot 运行状态
- Telegram 中 /start 是否正常响应
- 监控的 AWS 账户和实例数量
- systemd 服务状态
