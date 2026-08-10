## 这次改了什么 / What changed

<!-- 用一句话说明用户能感知到的变化。 / Describe the user-visible outcome in one sentence. -->

## 安全影响 / Safety impact

- [ ] 只读扫描 / Read-only scanning
- [ ] 计划写入 / Plan mutation
- [ ] 文件移动或恢复 / File move or restore
- [ ] 永久删除 / Permanent deletion
- [ ] 不涉及生命周期动作 / No lifecycle action involved

## 验证 / Verification

- [ ] `python scripts/doctor.py --project-only`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `node --check assets/dashboard/i18n.js`
- [ ] `node --check assets/dashboard/app.js`
- [ ] 中英界面与 375px 响应式检查 / Chinese, English, and 375px responsive checks

## 兼容性 / Compatibility

<!-- 说明数据库、计划文件、归档包或已有安装入口是否受影响。 / Note any database, plan, archive, or installation compatibility impact. -->
