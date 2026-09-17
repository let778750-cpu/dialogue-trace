# Contributing

[中文说明](#中文说明) · [README](README.md)

Use an isolated development environment and keep test data separate from real research archives. The commands below reproduce the Python version and dependency setup used by Windows CI. You need a bootstrap Python installation and Node.js 22; uv downloads CPython 3.12.11 for the project environment.

Run from the repository root:

```powershell
python -m pip install uv==0.8.22
uv python install 3.12.11
uv venv --python 3.12.11 .venv
uv pip sync --python .venv\Scripts\python.exe integrations/release-requirements.lock.txt
uv pip install --python .venv\Scripts\python.exe --no-deps --no-build-isolation .
.\.venv\Scripts\python.exe -m pytest tests -q
node --test (Get-ChildItem tools/obsidian/graph/*.test.cjs).FullName
.\.venv\Scripts\python.exe scripts/check_release.py
.\.venv\Scripts\python.exe scripts/build_obsidian.py --output build/obsidian
```

The component builder expects a new output directory. If `build/obsidian` already exists, choose another build directory so the earlier output remains available for comparison.

Changes to capture, message ownership, runs or knowledge publication should include regression cases with explicit sources. Preserve event identities, request idempotency and version checks. Use synthetic fixtures in tests and issue reports; do not submit private conversations, credentials or local instance configuration. A useful issue includes the version, reproduction steps, expected behavior and what actually happened.

When an allowlisted source file changes, regenerate `release-manifest.json` with `.\.venv\Scripts\python.exe scripts/check_release.py --write`, then run the checker without `--write`. The file list excludes generated build metadata and private instance data. Review the allowlist before adding file types. Keep ZIP archives in GitHub Releases rather than Git history, and preserve third-party license notices.

Documentation should introduce the reader's task before implementation details. Explain where to run a command, which values need changing and how to recognize its result. Use complete paragraphs for explanations and lists for actual steps or comparisons. Keep the English and Chinese homepages aligned in meaning, while writing each naturally in its own language. Describe test results within their observed scope: successful execution does not establish a scientific conclusion or a measured usability benefit.

## 中文说明

请在独立开发环境中工作，将测试数据与真实研究资料分开。上面的命令从仓库根目录运行，使用与 Windows CI 相同的 Python 版本和锁定依赖。你需要先准备可运行的 Python 和 Node.js 22，uv 会另行下载项目所用的 CPython 3.12.11。

组件构建需要使用新的输出目录。如果 `build/obsidian` 已存在，请换一个位置保存本次构建，以便保留前一次结果作比较。

涉及采集、消息归属、运行记录或知识发布的改动，应补充有明确来源的回归案例，并保留事件身份、请求幂等和版本检查。测试与问题报告使用合成材料，不提交私人对话、凭据或本机实例配置。报告问题时，请说明版本、复现步骤、预期行为和实际结果。

修改发行清单中的文件后，运行 `.\.venv\Scripts\python.exe scripts/check_release.py --write` 更新哈希，再运行不带 `--write` 的命令检查一致性。新增文件类型前应检查允许名单，ZIP 放在 GitHub Releases 中，第三方许可证声明需要保留。

文档应先解释读者正在完成的任务，再介绍相关实现。每组命令都要说明运行位置、需要替换的参数和判断结果的方法。说明文字使用连贯段落，步骤与比较才使用列表；避免用斜杠连接多个概念，或把完整说明压缩成口号。中英文主页保持含义一致，但各自按照自然的语言习惯写作。报告验证结果时，应明确实测范围，不能把程序执行成功写成科学结论成立，也不能把自动测试通过写成人的使用效率已经提高。
