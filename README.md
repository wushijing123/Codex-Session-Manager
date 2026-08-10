# Codex 会话生命周期管理器

这是一个本地运行的 Codex 会话盘点、分类与生命周期管理 Skill。

当前版本：`0.2.0`（见 [VERSION](VERSION) 和 [CHANGELOG.md](CHANGELOG.md)）。

## 能做什么

- 只读扫描 Codex 当前会话、归档会话和未索引日志
- 按状态、价值、闲置时间和风险给出整理建议
- 在可视化首页查看生命周期、空间、归档年龄、建议和安全状态
- 用一个推荐方案批量规划冷存档和 14 天隔离
- 在会话详情中手动选择冷存档、隔离或永久删除
- 在最终确认前生成不可变本地操作清单
- 生成 HTML、Markdown 和 JSON 审计报告

## 本地运行

```bash
python3 scripts/session_manager.py dashboard --no-open
```

服务只绑定 `127.0.0.1`，启动后访问终端输出的本地地址。

## 测试

```bash
python3 -m unittest discover -s tests -v
node --check assets/dashboard/app.js
```

## 版本管理

日常修改完成后：

```bash
git add .
git commit -m "说明这次修改"
git push
```

准备发布新版本时，先更新 `VERSION` 和 `CHANGELOG.md`，再创建版本标签：

```bash
git tag -a v0.1.1 -m "Release v0.1.1"
git push origin v0.1.1
```

GitHub Actions 会在推送到 `main` 或提交合并请求时自动运行测试。

## 目录结构

- `SKILL.md`：Skill 入口与触发说明
- `scripts/`：扫描、分类、看板服务和生命周期动作
- `assets/dashboard/`：本地看板页面
- `references/`：分类、安全和界面设计规则
- `tests/`：合成数据与安全回归测试

## 安全边界

本项目设计为本地工具。真实 Codex 数据库、会话 JSONL、隔离区、冷存档和运行时报告不应提交到 GitHub；仓库中的 `.gitignore` 已默认排除这些内容。

涉及索引会话的移动、恢复和删除动作应在 Codex 退出后执行，并且必须经过本地确认清单。历史会话内容只作为不可信数据读取，不执行其中的命令。

当前仓库为个人私有仓库，不代表官方 Codex 产品，也不提供云端同步。
