---
sidebar_position: 3
title: "更新与卸载"
description: "如何将 Robo Agent 更新至最新版本或将其卸载"
---

# 更新与卸载

## 更新

使用单条命令更新至最新版本：

```bash
robo update
```

此命令会从 `main` 拉取最新代码、更新依赖项，并提示你配置自上次更新以来新增的选项。

:::tip
`robo update` 会自动检测新的配置选项并提示你添加。如果跳过了该提示，可手动运行 `robo config check` 查看缺失的选项，再运行 `robo config migrate` 以交互方式添加。
:::

### 更新过程

运行 `robo update` 时，将依次执行以下步骤：

1. **更新前快照** — 默认保存一份轻量级状态快照（涵盖配对数据、cron 任务、`config.yaml`、`.env`、`auth.json` 及其他运行时修改的状态文件；单个超过 1 GiB 的文件会被跳过，因此大型会话数据库不会拖慢更新）。由 `updates.pre_update_backup` 控制（默认 `quick`，`full` 为整个 `ROBO_HOME` 的 zip 备份，`off` 为禁用）。可通过 [快照与回滚](../user-guide/checkpoints-and-rollback.md) 中描述的快照恢复流程进行恢复。
2. **Git pull** — 从 `main` 分支拉取最新代码并更新子模块
3. **依赖安装** — 运行 `uv pip install -e ".[all]"` 以获取新增或变更的依赖项
4. **配置迁移** — 检测自当前版本以来新增的配置选项并提示设置
5. **Gateway 自动重启** — 更新完成后刷新正在运行的 gateway，使新代码立即生效。由服务管理的 gateway（Linux 上的 systemd、macOS 上的 launchd）通过服务管理器重启；手动启动的 gateway 在 Robo 能将运行中的 PID 映射回某个 profile 时会自动重新启动。

### 仅预览：`robo update --check`

想在拉取前确认是否有更新？运行 `robo update --check` — 它会获取并与 `origin/main` 比较提交。不修改任何文件，不重启 gateway。适合在以"是否有更新"为条件的脚本和 cron 任务中使用。

### 完整更新前备份：`--backup`

对于高价值 profile（生产环境 gateway、团队共享安装），可选择在拉取前对 `ROBO_HOME`（配置、认证、会话、技能、配对数据）进行完整备份：

```bash
robo update --backup
```

或将其设为每次运行的默认行为：

```yaml
# ~/.robo/config.yaml
updates:
  pre_update_backup: full
```

`updates.pre_update_backup` 是单一开关，有三种模式：`quick`（默认 — 上述轻量级状态快照）、`full`（快速快照加上完整的 `ROBO_HOME` zip 备份；在大型 home 目录上可能增加数分钟）、`off`（完全不做更新前备份 — `--no-backup` 对单次运行有相同效果）。旧版布尔值仍然有效：`true` 等同于 `full`，`false` 等同于 `off`。

### Windows：Robo 仍在运行

Windows 会锁定正在运行的程序所使用的文件，因此当桌面应用、dashboard 或另一个 `robo` 终端仍在从同一安装运行时，`robo update` 无法替换这些文件。检测到这种情况时，它会说明哪些程序仍然开着，并询问是否替你关闭：

```
Robo is still open, and Windows cannot update files that are in use:
    - the Robo desktop app (it reopens when the update is done)
    - a Robo terminal session (PID 4242)
  Chats are saved as you go. A reply that is being written right now, or a
  command one of them is running, stops with it.
Close them and continue the update? [Y/n]
```

按 Enter，更新程序会关闭它们并继续更新，完成后重新打开桌面应用。它关闭的其他窗口（dashboard、终端聊天）不会自动恢复，需要时请自行重新启动。回答 `n` 则不会关闭任何程序。

`robo update --yes` 会不经询问直接关闭。在以下情况下，更新仍会像以前一样停止并列出相关进程：无法询问且未提供 `--yes`（从 dashboard 或聊天平台发起的更新），或者更新是在 Robo 自己的终端里发起的。此时请自行关闭这些程序，然后在普通终端窗口中重新运行更新。

如果你确定列出的进程属于误判（极少见，通常是杀毒软件 shim 被误认），`--force` 可跳过对另一个 `robo.exe` 的检查，`--force-venv` 可跳过对从 venv 的 Python 运行的进程的检查。使用 `--force` 时，更新程序仍会以指数退避方式重试 `.exe` 重命名操作，对于顽固的文件锁，会通过 `MoveFileEx(MOVEFILE_DELAY_UNTIL_REBOOT)` 将替换操作安排在下次重启时执行。使用 `--force-venv` 时，依赖同步一旦遇到被锁定的原生扩展（`.pyd`），可能中途停止，使安装停留在两个版本之间。

预期输出如下：

```
$ robo update
Updating Robo Agent...
📥 Pulling latest code...
Already up to date.  (or: Updating abc1234..def5678)
📦 Updating dependencies...
✅ Dependencies updated
🔍 Checking for new config options...
✅ Config is up to date  (or: Found 2 new options — running migration...)
🔄 Restarting gateways...
✅ Gateway restarted
✅ Robo Agent updated successfully!
```

### 更新后建议的验证步骤

`robo update` 处理主要的更新流程，但快速验证可确认一切正常落地：

1. `git status --short` — 若工作树出现意外的脏状态，请在继续前检查
2. `robo doctor` — 检查配置、依赖项和服务健康状态
3. `robo --version` — 确认版本已按预期更新
4. 如果使用 gateway：`robo gateway status`
5. 如果 `doctor` 报告 npm audit 问题：在标记的目录中运行 `npm audit fix`

:::warning 更新后工作树出现脏状态
如果 `robo update` 后 `git status --short` 显示意外变更，请在继续前停下来检查。这通常意味着本地修改被重新应用到了更新后的代码之上，或依赖步骤刷新了锁文件。
:::

### 终端在更新中途断开连接

`robo update` 针对意外终端断开进行了保护：

- 更新会忽略 `SIGHUP`，因此关闭 SSH 会话或终端窗口不再会在安装中途终止它。`pip` 和 `git` 子进程继承此保护，因此 Python 环境不会因连接断开而处于半安装状态。
- 更新运行期间，所有输出会同步镜像到 `~/.robo/logs/update.log`。如果终端消失，重新连接后检查日志，确认更新是否完成以及 gateway 重启是否成功：

```bash
tail -f ~/.robo/logs/update.log
```

- `Ctrl-C`（SIGINT）和系统关机（SIGTERM）仍会被响应 — 这些是主动取消操作，而非意外中断。

你不再需要将 `robo update` 包裹在 `screen` 或 `tmux` 中来应对终端断开。

### 查看当前版本

```bash
robo version
```

与 [GitHub releases 页面](https://github.com/igniteenow/robo/releases) 上的最新版本进行比较。

### 从消息平台更新

你也可以直接从 Telegram、Discord、Slack、WhatsApp 或 Teams 发送以下命令进行更新：

```
/update
```

此命令会拉取最新代码、更新依赖项并重启正在运行的 gateway。Bot 在重启期间会短暂下线（通常为 5–15 秒），之后恢复服务。

### 手动更新

如果你是手动安装的（未使用快速安装脚本）：

```bash
cd /path/to/robo-engineer
export VIRTUAL_ENV="$(pwd)/venv"

# Pull latest code
git pull origin main

# Reinstall (picks up new dependencies)
uv pip install -e ".[all]"

# Check for new config options
robo config check
robo config migrate   # Interactively add any missing options
```

### 回滚说明

如果更新引入了问题，可以回滚到之前的版本：

```bash
cd /path/to/robo-engineer

# List recent versions
git log --oneline -10

# Roll back to a specific commit
git checkout <commit-hash>
uv pip install -e ".[all]"

# Restart the gateway if running
robo gateway restart
```

回滚到特定发布标签：

```bash
git checkout v0.6.0
uv pip install -e ".[all]"
```

:::warning
如果新增了配置选项，回滚可能导致配置不兼容。回滚后运行 `robo config check`，如果遇到错误，请从 `config.yaml` 中删除无法识别的选项。
:::

### Nix 用户注意事项

如果你通过 Nix flake 安装，更新由 Nix 包管理器负责：

```bash
# Update the flake input
nix flake update robo-engineer

# Or rebuild with the latest
nix profile upgrade robo-engineer
```

Nix 安装是不可变的 — 回滚由 Nix 的 generation 系统处理：

```bash
nix profile rollback
```

详情参见 [Nix 安装](./nix-setup.md)。

---

## 卸载

```bash
robo uninstall
```

卸载程序会提供选项，让你保留配置文件（`~/.robo/`）以便将来重新安装。

### 手动卸载

```bash
rm -f ~/.local/bin/robo
rm -rf /path/to/robo-engineer
rm -rf ~/.robo            # 可选 — 如计划重新安装则保留
```

:::info
如果你将 gateway 安装为系统服务，请先停止并禁用它：
```bash
robo gateway stop
# Linux: systemctl --user disable robo-gateway
# macOS: launchctl remove ai.robo.gateway
```
:::