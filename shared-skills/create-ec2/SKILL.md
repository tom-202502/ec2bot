---
name: create-ec2
description: 基于现有 EC2 实例或 AMI 创建新实例，自动完成初始化配置。适用于 AWS 环境扩容、灾备、环境克隆。
---

# 创建 EC2 实例

基于已有实例的 AMI 或指定 AMI，创建配置一致的新 EC2 实例，并完成初始化。

## 触发词
创建机器、新建实例、克隆服务器、配置新机器、扩容

## 参数
- `$ARGUMENTS`：源实例 ID 或 AMI ID（可选）
- 如 `/create-ec2 i-0320626a45b7bd57e` 或 `/create-ec2 ami-0abcdef1234567890`

## 前提条件
- AWS CLI 已配置（或提供 AK/SK）
- IAM 权限：ec2:RunInstances, ec2:CreateImage, ec2:DescribeInstances, ec2:CreateTags
- 知道源实例 ID 或 AMI ID
- 知道目标区域、子网、安全组

## 执行流程

### 1. 查询源实例配置
```bash
aws ec2 describe-instances \
  --instance-ids <源实例ID> \
  --query 'Reservations[].Instances[].{
    Type:InstanceType,
    AMI:ImageId,
    SubnetId:SubnetId,
    SG:SecurityGroups[].GroupId,
    KeyName:KeyName,
    BlockDevices:BlockDeviceMappings
  }' \
  --output json
```

向用户确认：机型、子网、安全组、磁盘大小是否需要调整。

### 2. 创建 AMI（如无现成 AMI）
```bash
aws ec2 create-image \
  --instance-id <源实例ID> \
  --name "clone-<名称>-$(date +%Y%m%d)" \
  --no-reboot

# 等待 AMI 就绪
aws ec2 wait image-available --image-ids <AMI_ID>
```

### 3. 创建新实例
```bash
aws ec2 run-instances \
  --image-id <AMI_ID> \
  --instance-type <机型> \
  --key-name <密钥对> \
  --subnet-id <子网ID> \
  --security-group-ids <安全组ID> \
  --block-device-mappings '[{
    "DeviceName": "/dev/xvda",
    "Ebs": {
      "VolumeSize": <磁盘GB>,
      "VolumeType": "gp3",
      "Iops": 3000
    }
  }]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=<实例名称>}]' \
  --count 1
```

### 4. 等待实例就绪
```bash
aws ec2 wait instance-running --instance-ids <新实例ID>

# 获取公网 IP
aws ec2 describe-instances \
  --instance-ids <新实例ID> \
  --query 'Reservations[].Instances[].PublicIpAddress' \
  --output text
```

### 5. SSH 初始化配置

登录新实例后执行：

```bash
# 配置 root 密码（用户提供或自动生成）
echo 'root:<密码>' | sudo chpasswd

# 开启密码登录（可选）
sudo sed -i 's/^PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# 安装 Node Exporter（如需监控）
VERSION=1.8.2
cd /tmp
curl -sLO https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/node_exporter-${VERSION}.linux-amd64.tar.gz
tar xzf node_exporter-${VERSION}.linux-amd64.tar.gz
sudo cp node_exporter-${VERSION}.linux-amd64/node_exporter /usr/local/bin/
sudo tee /etc/systemd/system/node_exporter.service > /dev/null <<'EOF'
[Unit]
Description=Node Exporter
After=network.target
[Service]
Type=simple
ExecStart=/usr/local/bin/node_exporter
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter

# 放行防火墙 9100 端口
sudo firewall-cmd --add-port=9100/tcp --permanent 2>/dev/null && sudo firewall-cmd --reload 2>/dev/null
```

### 6. 输出汇总

| 项目 | 值 |
|------|-----|
| 新实例 ID | i-0xxxxxxxxxxxxxxxxx |
| 实例名称 | new-server-01 |
| 机型 | c5.xlarge |
| 区域/AZ | ap-southeast-1a |
| 公网 IP | 54.169.xxx.xxx |
| 内网 IP | 172.31.xx.xx |
| AMI | ami-0xxxxxxxxxxxxxxxxx |
| 磁盘 | 50GB gp3 |
| SSH | `ssh -i key.pem ubuntu@54.169.xxx.xxx` |
| Node Exporter | active (port 9100) |

## 注意事项
- 创建 AMI 需要时间（几分钟到十几分钟），取决于磁盘大小
- 部分区域 EIP 配额可能已满，可使用自动分配的公网 IP
- 如果使用 Prometheus EC2 自动发现，新实例会自动被纳入监控
- 创建完成后建议运行 `/server-check` 验证新实例健康状态
