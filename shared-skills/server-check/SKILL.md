---
name: server-check
description: 批量 SSH 巡检多台 Linux 服务器的健康状态（CPU/内存/磁盘/服务）。适用于任何 SSH 可达的 Linux 服务器集群。
---

# 服务器批量巡检

批量 SSH 连接多台 Linux 服务器，采集 CPU/内存/磁盘/服务状态，输出异常汇总表。

## 触发词
巡检、检查服务器、服务器状态、health check、批量检查

## 参数
- `$ARGUMENTS`：服务器组名称或 IP 列表（可选）
- 如 `/server-check production` 或 `/server-check 10.0.0.1,10.0.0.2,10.0.0.3`

## 前提条件
- SSH 密钥或密码可连接到目标服务器
- 用户需提供服务器清单（IP + SSH 用户 + 密钥/密码）

## 服务器清单格式

用户可以通过以下任一方式提供清单：

**方式 1：对话中直接提供**
```
IP: 10.0.0.1, 用户: ubuntu, 密钥: /path/to/key.pem
IP: 10.0.0.2, 用户: ec2-user, 密钥: /path/to/key2.pem
```

**方式 2：配置文件（YAML）**
```yaml
# servers.yaml
groups:
  production:
    ssh_user: ubuntu
    ssh_key: /path/to/key.pem
    servers:
      - {ip: 10.0.0.1, name: web-01}
      - {ip: 10.0.0.2, name: web-02}
  staging:
    ssh_user: ec2-user
    ssh_key: /path/to/key2.pem
    servers:
      - {ip: 10.0.1.1, name: stg-01}
```

## 巡检项目

对每台服务器并发执行以下检查：

```bash
# 主机名 + 在线时长
hostname && uptime

# 内存使用
free -h | head -2

# 根分区磁盘使用
df -h / | tail -1

# CPU 负载
top -bn1 | head -5

# 指定服务状态（可选，如 node_exporter, nginx, docker 等）
systemctl is-active <service_name> 2>/dev/null
```

通用 SSH 参数：`-o StrictHostKeyChecking=no -o ConnectTimeout=10`

## 异常判定阈值

| 指标 | 告警阈值 | 标记 |
|------|---------|------|
| 内存使用率 | > 85% | MEM! |
| 磁盘使用率 | > 85% | DISK! |
| CPU 负载 | > CPU 核数 | CPU! |
| 指定服务 | inactive/不存在 | SVC! |
| SSH 连接 | 超时/拒绝 | CONN! |

阈值可根据用户需求调整。

## 输出格式

### 汇总表格

| 服务器 | IP | CPU 负载 | 内存 | 磁盘 | 服务 | 状态 |
|--------|-----|---------|------|------|------|------|
| web-01 | 10.0.0.1 | 0.5/4 | 62% | 45% | active | OK |
| web-02 | 10.0.0.2 | 4.2/2 | 91% | 88% | active | CPU! MEM! DISK! |
| stg-01 | 10.0.1.1 | - | - | - | - | CONN! |

### 底部统计
```
共巡检 3 台 | 正常 1 台 | 异常 2 台
异常详情：
  web-02: CPU 负载超标(4.2/2核)、内存 91%、磁盘 88%
  stg-01: SSH 连接超时
```

## 扩展（可选）

如果用户环境有 Prometheus，可追加验证监控数据源：
```bash
curl -s 'http://<prometheus>:9090/api/v1/query?query=up' | python3 -c "
import sys,json
for r in json.load(sys.stdin).get('data',{}).get('result',[]):
    print(r['metric'].get('instance','?'), r['value'][1])
"
```
