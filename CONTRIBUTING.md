# Contributing / 参与开发

Use Python 3.12 and Node.js 22. Install the locked dependencies in a private virtual environment, then run the Python and JavaScript commands in the README. Development and test data must remain separate from real research archives.

使用 Python 3.12、Node.js 22，在独立虚拟环境安装锁定依赖，然后运行主页中的 Python/JavaScript 测试。开发数据与真实研究库分离。

Changes affecting capture, ownership, runs or publication need source-backed regression cases. Use synthetic fixtures. Do not submit real transcripts, screenshots of private work, caches, credentials or local instance configuration. Include reproduction steps, expected behavior and actual behavior in issues.

涉及采集、归属、运行或发布的改动，需要具有来源依据的回归案例。只提交合成材料，不提交真实对话、私人截图、缓存、凭据或实例配置。Issue 请写复现步骤、预期与实际行为。

Preserve event identity, request idempotency, version checks and third-party notices. A passing tool run is not scientific support. A passing automated test is not a human usability result. Label validation scope explicitly.

保留事件身份、请求幂等、版本检查和第三方声明。工具执行成功不等于科学支持，自动测试通过不等于人工使用效果；请明确验证范围。

When release files change, regenerate `release-manifest.json` with `python scripts/check_release.py --write`, then run the checker without `--write`. Review the allowlist before adding file types. Release ZIPs belong in GitHub Releases, not the source tree.

发行文件变更后，运行 `python scripts/check_release.py --write` 更新清单，再不带 `--write` 校验。新增文件类型前审阅允许名单。ZIP 放在 GitHub Releases，不提交到源码目录。
