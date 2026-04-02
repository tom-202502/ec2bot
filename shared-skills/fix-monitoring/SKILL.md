---
name: fix-monitoring
description: 排查并修复 Prometheus 监控采集异常（target down / scrape error）。适用于所有使用 Prometheus + Node Exporter 的环境。
---

# 修复 Prometheus 监控异常

排查并修复 Prometheus target 采集失败的问题。

## 触发词
监控报错、target down、scrape error、Node Exporter 异常、采集失败

## 参数
- `$ARGUMENTS`：Prometheus 地址或目标实例信息（可选）
- 如 `/fix-monitoring http://prometheus:9090` 或 `/fix-monitoring 10.0.0.5`

## 前提条件
- 知道 Prometheus 服务器地址（或能访问 Prometheus UI/API）
- 能 SSH 到目标服务器
- 了解网络拓扑（安全组/防火墙规则）

## 排查流程

### 1. 获取异常 Target 列表

从 Prometheus API 查询不健康的 target：
```bash
curl -s 'http://<prometheus>:9090/api/v1/targets' | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data.get('data',{}).get('activeTargets',[]):
    if t['health'] != 'up':
        print(f\"{t['labels'].get('instance','?')}  {t['health']}  {t.get('lastError','')}\")
"
```

### 2. 根据错误类型处理

#### 错误 A："no route to host" — 防火墙阻挡

目标机器防火墙未放行 9100 端口。

```bash
# 登录目标服务器

# CentOS / RHEL (firewalld)
sudo firewall-cmd --add-port=9100/tcp --permanent
sudo firewall-cmd --reload

# Ubuntu / Debian (ufw)
sudo ufw allow 9100/tcp

# 通用 (iptables)
sudo iptables -I INPUT -p tcp --dport 9100 -j ACCEPT
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

验证：
```bash
curl -s http://localhost:9100/metrics | head -5
```

#### 错误 B："connection refused" — Node Exporter 未运行

服务未启动或未安装。

```bash
# 检查服务状态
systemctl is-active node_exporter

# 如果未安装，安装 Node Exporter
VERSION=1.8.2
cd /tmp
curl -sLO https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/node_exporter-${VERSION}.linux-amd64.tar.gz
tar xzf node_exporter-${VERSION}.linux-amd64.tar.gz
sudo cp node_exporter-${VERSION}.linux-amd64/node_exporter /usr/local/bin/

# 创建 systemd service
sudo tee /etc/systemd/system/node_exporter.service > /dev/null <<'EOF'
[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/node_exporter
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable node_exporter
sudo systemctl start node_exporter
```

验证：
```bash
systemctl status node_exporter
curl -s http://localhost:9100/metrics | head -5
```

#### 错误 C："context deadline exceeded" — 网络不可达

Prometheus 到目标的网络不通。

排查步骤：
1. 从 Prometheus 所在机器测试连通性：
   ```bash
   curl -m 5 http://<目标IP>:9100/metrics
   telnet <目标IP> 9100
   ```
2. 检查云平台安全组（AWS Security Group / 阿里云安全组 / ...）是否放行 9100
3. 检查目标机器内部防火墙
4. 如果 SSH 也不通 → 需要通过云平台控制台 / Serial Console / SSM 介入

### 3. 验证修复

等待 1-2 个采集周期（通常 15-60 秒），然后检查：
```bash
curl -s 'http://<prometheus>:9090/api/v1/targets' | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data.get('data',{}).get('activeTargets',[]):
    if '<目标IP>' in t['labels'].get('instance',''):
        print(f\"Health: {t['health']}, Last Scrape: {t['lastScrape']}\")
"
```

### 4. 输出汇总

| 目标 | 原始错误 | 修复操作 | 当前状态 |
|------|---------|---------|---------|
| 10.0.0.5:9100 | connection refused | 安装并启动 Node Exporter | UP |

## 常见 Node Exporter 版本
- 最新稳定版：v1.8.2
- 下载地址：https://github.com/prometheus/node_exporter/releases
