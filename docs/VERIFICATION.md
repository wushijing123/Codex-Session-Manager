# 验证说明

以下内容记录本仓库公开发行前后用于检查文档和入口命令的结果。

## v0.7.0（2026-10-21）

本地 113 项单元测试通过、项目 Doctor 通过，两份 Dashboard JavaScript 语法检查通过。桌面与 375px 浏览器验证覆盖主题、中英文、主题记忆及跨页勾选；备份取消与位置选择使用虚构数据验证，未以真实会话测试破坏性操作。发行包为 `Codex-Session-Manager-v0.7.0.zip`，包内保留兼容的 Skill 根目录。

下方为 v0.6.0 历史发行及旧版冷存档恢复证据，不代表当前 ZIP 恢复承诺。GitHub CI 结果按提交另行查看。

## 已验证

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `python3 scripts/install_skill.py` | 通过 | 默认只安装 Codex 入口 |
| `python3 scripts/install_skill.py --targets codex workbuddy` | 通过 | 只创建指定入口，不覆盖已有目录 |
| `python3 scripts/install_skill.py --targets all --verify` | 通过 | 四个可用入口都指向唯一维护源 |
| `python3 scripts/install_skill.py --dry-run` | 通过 | 当前环境输出 `OK codex ...`，用于预览安装动作与冲突提示 |
| `python3 scripts/install_skill.py --verify` | 通过 | 当前 Codex 入口指向唯一维护源 |
| `python3 scripts/doctor.py --project-only` | 通过 | 项目检查通过 |
| `python3 -m unittest discover -s tests -v` | 通过 | 合成回归测试全部通过 |
| `node --check assets/dashboard/i18n.js` | 通过 | 语法检查通过 |
| `node --check assets/dashboard/app.js` | 通过 | 语法检查通过 |
| `python3 scripts/package_release.py --output-dir dist` | 通过 | 生成 `dist/codex-session-lifecycle-manager-v0.6.0.zip` |
| macOS 真实冷存档恢复闭环 | 通过 | 在 Codex 运行时启动 `--verify-closed-loop`，退出后恢复原始 JSONL 与数据库索引；原文件 SHA-256、Session ID、标题、归档状态和创建/更新时间字段保持一致 |

真实恢复验证必须在 Codex 仍运行时启动，并显式使用 `--verify-closed-loop`。助手确认“启动时正在运行 → 完全退出 → 内容和索引恢复成功”后，才会写入本机能力标记；手工创建标记文件不属于验证。

### 真实恢复证据（2026-08-23）

- 使用专门创建的合成测试会话，不含真实业务内容
- 冷存档包摘要、压缩文件摘要和解压后原日志摘要全部通过
- 恢复后 JSONL 字节数与 SHA-256 和冷存档前完全一致
- 数据库行恢复为 `archived=1`，原 `created_at`、`updated_at`、`archived_at` 及毫秒字段未改变
- 用户消息与 Codex 最终回复均可从恢复后的 JSONL 重新解析
- 冷存档包在成功提交后移除，恢复审计摘要通过校验
- 本机能力标记仅在助手观察到“启动时运行中 → 完全退出 → 恢复成功”后写入，权限为 `0600`
- 新版看板重新扫描后将该会话识别为普通已归档，并启用本机恢复能力

## 暂未验证

- 永久删除的实机全流程
- Windows 运行链路

## 结论

公开发行文案只描述已验证边界；任何未进入上表“已验证”的能力，都应继续标记为待确认或待实测。
