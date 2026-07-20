# Docker 安全基线与残余风险

> S2-17: 记录 Docker 安全基线与残余风险

## 默认安全策略

OmniEvolve 的 `DockerBackend` 默认启用以下安全措施：

| 策略 | 配置 | 效果 |
|------|------|------|
| 网络隔离 | `network_mode=none` | 容器无法访问任何网络 |
| 只读根文件系统 | `read_only=True` | 容器文件系统不可写入（除 /tmp） |
| 非 root 用户 | `user=1000:1000` | 以非特权用户运行 |
| 能力删除 | `cap_drop=["ALL"]` | 移除所有 Linux capabilities |
| 禁止提权 | `no-new-privileges` | 禁止 setuid/setgid 提权 |
| PID 限制 | `pids_limit=64` | 防止 fork bomb |
| 内存限制 | `mem_limit=512m` | 512MB 上限 |
| CPU 限制 | `cpu_limit=1.0` | 1 个 CPU 核心 |
| 临时文件系统 | `tmpfs=/tmp:256m` | /tmp 可写但有大小限制 |
| 超时 | `timeout=30s` | 墙钟超时 |
| 环境变量白名单 | `allowed_env` | 仅允许指定的环境变量传入 |

## 残余风险

### 1. Docker 守护进程逃逸 (CVE 风险)

**风险等级**: 中
**缓解**: 保持 Docker 引擎更新到最新补丁版本
**监控**: `omnievolve doctor` 检查 Docker 连接状态

### 2. 内核共享

**风险等级**: 低
**说明**: 容器与宿主机共享内核，内核漏洞可能被利用
**缓解**: 使用最新 LTS 内核，启用 seccomp/AppArmor
**长期方案**: 迁移到 gVisor/Firecracker (HardenedBackend)

### 3. 资源竞争

**风险等级**: 低
**说明**: 多个容器同时运行可能竞争宿主机资源
**缓解**: 严格的资源限制（CPU/内存/PID）

### 4. 侧信道攻击

**风险等级**: 极低
**说明**: CPU 缓存侧信道（Spectre/Meltdown 变种）
**缓解**: 现代 CPU 微码更新已缓解主要变种

### 5. 镜像供应链

**风险等级**: 低
**说明**: 基础镜像 `python:3.12-slim` 由 Docker Hub 维护
**缓解**: 
- 使用固定 digest: `python:3.12-slim@sha256:...`
- 定期重建镜像
- 扫描已知漏洞 (`docker scan`)

## 何时不应使用 DockerBackend

1. **开发/测试快速迭代**: 使用 `--trusted` + `TrustedSubprocessBackend`
2. **强隔离需求**: 部署 `HardenedBackend` (gVisor/Firecracker)
3. **无 Docker 环境**: 使用 `TrustedSubprocessBackend`（仅可信代码）

## TrustedSubprocessBackend 警告

`--trusted` 标志绕过所有安全隔离。候选代码在宿主机上以当前用户权限运行。

**仅在以下情况使用**:
- 本地开发和测试
- 候选代码来自完全可信来源
- 临时实验探索
