---
name: add-user
description: 批量给多台 Linux 服务器添加用户账户，自动生成强密码并逐台验证。适用于人员入职、权限开通等场景。
---

# 批量添加 Linux 用户

批量 SSH 连接多台服务器，创建用户账户 + 自动生成强密码 + 逐台验证登录。

## 触发词
添加用户、创建用户、创建账号、批量加用户、开通账户

## 参数
- `$ARGUMENTS`：`<用户名>` 或 `<用户名> <服务器组>`
- 如 `/add-user zhangsan` 或 `/add-user zhangsan production`

## 前提条件
- SSH 密钥或密码可连接到目标服务器（需 sudo 权限）
- 用户需提供目标服务器清单（IP + SSH 用户 + 密钥/密码）
- 目标服务器需开启 SSH PasswordAuthentication（用于验证新账户）

## 执行流程

### 1. 确认参数
- **用户名**：待创建的 Linux 用户名
- **目标服务器**：通过对话提供或从配置文件读取
- **密码**：自动生成 16 位随机密码（大小写字母 + 数字）
- **是否赋予 sudo 权限**：默认 **不赋予**，除非用户明确要求

### 2. 生成密码
```python
import random, string
password = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
```
所有服务器使用同一密码，方便管理。

### 3. 批量执行（并发 SSH）

对每台服务器执行：
```bash
sudo useradd -m -s /bin/bash <用户名>
echo '<用户名>:<密码>' | sudo chpasswd
id <用户名>
```

如需 sudo 权限（用户明确要求时）：
```bash
sudo usermod -aG sudo <用户名>   # Debian/Ubuntu
sudo usermod -aG wheel <用户名>  # CentOS/RHEL
```

### 4. 逐台验证
使用新用户 + 密码通过 SSH 登录验证：
```bash
sshpass -p '<密码>' ssh -o StrictHostKeyChecking=no <用户名>@<IP> "whoami && echo OK"
```

### 5. 输出汇总

| 服务器 | IP | 用户 | 密码 | sudo | 状态 |
|--------|-----|------|------|------|------|
| web-01 | 10.0.0.1 | zhangsan | aB3kL9mN... | 否 | OK |
| web-02 | 10.0.0.2 | zhangsan | aB3kL9mN... | 否 | OK |
| db-01 | 10.0.0.3 | zhangsan | aB3kL9mN... | 否 | FAIL: SSH 验证失败 |

### 6. 注意事项
- 操作前确认目标服务器 SSH `PasswordAuthentication` 是否为 `yes`
- 密码输出仅显示一次，建议用户立即保存
- 不同服务器组可能使用不同 SSH 密钥，注意正确匹配
- 执行 `useradd` 前检查用户是否已存在（`id <用户名>` 判断）
