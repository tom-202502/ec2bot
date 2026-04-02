---
name: ec2bot-account
description: 为 EC2Bot 添加新的 AWS 账户并自动导入实例。当用户提到"添加 AWS 账户到 bot""新增监控账户"时使用。
---

# 添加 AWS 账户到 EC2Bot

引导用户添加新的 AWS 账户到 EC2Bot，自动写入凭证和配置，导入实例。

## 触发词
用户提到"添加 AWS 账户到 bot""新增监控账户""bot 加账户"时触发。

## 参数
- `$ARGUMENTS`：账户别名（可选），如 `/ec2bot-account 测试环境`

## 前提条件
- EC2Bot 已部署并运行
- 知道 config.yaml 和 .env 的路径
- 用户准备好新账户的 AWS Access Key/Secret Key

## 执行流程

### 1. 获取账户信息
询问用户：
- **账户别名**（显示名称，如"生产环境"、"测试环境"）
- **AWS 区域**（如 ap-southeast-1、us-east-1）
- **环境类型**（prod / test / dev）
- **AWS Access Key ID**
- **AWS Secret Access Key**
- **Session Token**（可选，使用临时凭证时需要）

### 2. 生成凭证变量名
根据别名自动生成 .env 变量名前缀，例如：
- 别名 "测试环境" → 前缀 `TEST_ENV`
- 变量：`TEST_ENV_KEY`、`TEST_ENV_SECRET`、`TEST_ENV_TOKEN`

### 3. 写入 .env
在 .env 文件末尾追加：
```bash
# 测试环境
TEST_ENV_KEY=AKIAXXXXXXXXXXXXXXXXXX
TEST_ENV_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TEST_ENV_TOKEN=
```

### 4. 写入 config.yaml
在 aws_accounts 列表中追加：
```yaml
- alias: "测试环境"
  region: ap-southeast-1
  auth: access_key
  environment: test
  access_key_env: TEST_ENV_KEY
  secret_key_env: TEST_ENV_SECRET
  session_token_env: TEST_ENV_TOKEN
  instances: []
```

### 5. 验证凭证有效性
```bash
AWS_ACCESS_KEY_ID=<AK> AWS_SECRET_ACCESS_KEY=<SK> aws ec2 describe-instances --region <region> --max-items 1 --output json
```
如果失败，提示用户检查 AK/SK 和 IAM 权限。

### 6. 重载配置
提示用户在 Telegram 中执行 `/account_reload`，或直接重启服务：
```bash
sudo systemctl restart ec2bot
```

### 7. 自动导入实例
提示用户在 Telegram 中执行：
```
/account_import <别名>
```

### 8. 输出汇总
- 账户别名、区域、环境
- 导入的实例数量
- 配置文件修改位置
