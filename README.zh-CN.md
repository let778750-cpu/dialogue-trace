<div align="center">

# Research Memory · 科研记忆

**把问题留下，把下一步为何这样走找回来。**

面向 Codex 的本地科研记忆 Skill，可选 Obsidian 时间线界面。

**简体中文** · [English](README.md) · [开始使用](#开始使用) · [案例](#一个问题跨两个任务) · [验证状态](VALIDATION.zh-CN.md)

![Windows](https://img.shields.io/badge/platform-Windows-0078D4)
![Preview](https://img.shields.io/badge/release-0.8.0--preview.2-7C5CBB)
![License](https://img.shields.io/badge/license-AGPL--3.0-blue)

</div>

科研讨论往往跨越多个窗口：一个任务补充了条件，另一个任务推翻了原来的解释，隔天回来又需要找出**改了什么、为什么改、依据在哪里**。

Research Memory 保留公开原话，以研究问题组织不同任务中的讨论。默认按顺序阅读，重要进展单独定位，命令输出与来源详情按需展开。

![合成温漂研究案例的实际时间线](assets/screenshots/timeline-light.jpg)

*实际 Obsidian 界面截图。温漂案例为中英双语合成内容，不代表科研证据。当前界面控件使用中文；文档提供中英双语，研究内容可以使用英文。*

## 可以做什么

| 研究中的需要 | 对应能力 |
|---|---|
| 同一个问题跨窗口继续 | 多个来源任务绑定稳定研究线，进入新一轮时读取有界增量简报。 |
| 一个窗口讨论多个问题 | 按连续完整消息区间归线；其他研究线可以引用原话，不复制成另一场讨论。 |
| 找回当时怎么讨论 | 用户蓝色、AI 紫色；宽屏左右、窄屏单列，保留顺序和全文。 |
| 定位有意义的进展 | 查看决定、修正、阻塞和研究断点，并追溯依据。 |
| 核对实际发生了什么 | 用户、AI、上下文、工具和生命周期分别展示；工具输入与结果分开。 |
| 纠正整理结果 | 通过版本和来源校验修改归属；可撤销，保留变更历史。 |
| 保留数据控制权 | 程序、私有数据和登记工作区分离；基础功能不要求 Obsidian。 |

## 一个问题跨两个任务

1. **任务 A：**“温升是否导致传感器漂移？”记录假设与对照条件。
2. **任务 A：**“预热时间没有统一。”保存新增约束，修正实验顺序。
3. **任务 B：**继续同一研究线，恢复前面的修正，发现还缺少重复试验。
4. **研究断点：**记录已知、未知和下一步；需要复核时再打开技术记录。

![工具记录的分类型详情](assets/screenshots/tool-details.jpg)

*输入、结果、来源和记录中的时间分开查看。演示工具数值明确标注为合成数据；缺失字段显示未知。*

![研究断点、已知未知与下一步](assets/screenshots/checkpoint.jpg)

初始化后，使用私有实例的 Python 复现案例：

```powershell
& 'C:/ResearchMemory/MyArchive/runtime/venv/Scripts/python.exe' `
  ./scripts/showcase.py --root 'C:/ResearchMemory/PublicDemo' --with-obsidian
```

指定新目录。此脚本只生成合成消息，不读取私人转录，不执行科研实验。用 Obsidian 打开生成的 `vault` 文件夹，在出现提示时自行启用组件，然后选择“打开研究时间线”。较小的 `scripts/demo.py` 案例无需 Obsidian。

### 视频演示

维护者录制的视频将在此处补充。[录制说明](docs/DEMO.md)提供镜头顺序和中英文主页的视频接入位置，现在即可复现截图案例。

## 开始使用

**环境要求：**Windows、Codex、可通过 `python` 调用的 Python 3.12+，以及初始化时的网络连接。Obsidian 可选。Node.js 只用于开发测试。

**1. 安装整个 Skill。** 在 Codex 中输入：

```text
使用 skill-installer，从 https://github.com/let778750-cpu/money-king
的仓库根目录安装 skill，安装名为 research-memory。
```

也可从 [Releases](https://github.com/let778750-cpu/money-king/releases) 下载 ZIP，将完整的 `research-memory` 文件夹放入 Codex 的 skill 目录，不能只复制 `SKILL.md`。安装后新开任务，以便宿主加载。

**2. 初始化私有数据。** 在 skill 文件夹内运行；替换示例路径：

```powershell
./scripts/install.ps1 -Workspace 'C:/Research/MyProject' `
  -DataDir 'C:/ResearchMemory/MyArchive'
./scripts/memory.ps1 --root 'C:/ResearchMemory/MyArchive' doctor
```

初始化将固定版本 CPython 3.12.11 和锁定依赖下载到私有实例，只登记指定工作区。需要完整界面时加 `-WithObsidian`；Obsidian 应用另行安装，随后打开打印出的 vault 路径。时间线不要求 Juggl，可选局部图使用 Juggl 1.5.0。

**3. 开始研究。**

```text
使用 $research-memory 继续研究温升与传感器漂移的关系。
先读取另一任务的相关进展，再提出下一步实验。
```

Skill 会显式进入研究任务、核对可访问转录并恢复研究线。安装完成不代表宿主每轮都触发 hooks；`doctor` 分别报告配置和实际观测。

[安装、升级与卸载](references/installation.zh-CN.md) · [后端接口](references/research-api.md) · [采集与成本](references/capture-and-trajectory.md)

## 记录什么，哪里消耗 token？

| 层次 | 执行方式 |
|---|---|
| 保存公开消息、工具记录、去重、来源校验、索引 | 脚本执行，不额外调用模型。 |
| 理解意义、归线建议、矛盾和下一步 | 当前模型按有限批次整理。 |
| 跨任务续接 | 先核对版本，有变化再读取简报；实际读取内容占用上下文。 |

首版没有后台“低价模型记录员”。Skill 是工作协议，不是常驻监听器。保存公开回答与过程说明，不采集隐藏推理；自动压缩仅记录边界，不复制内部私有摘要。

类型化详情借鉴 [DeepSeek Harness Trajectory](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/client/ui-trajectory) 的设计原则。本项目进一步组织跨任务研究线、依据与可撤销归属；不宣称支持 Harness 宿主，不推造 Codex 未公开的字段。

## 验证与边界

这是 **预览版**。[验证报告](VALIDATION.zh-CN.md)分别列出工程测试、实际界面观测和人工研究效果。测试通过不证明科学结论成立，也不证明找回任务已经提速。

真实双活跃任务 hooks 覆盖与十一类人工任务须独立验收。“耗时中位数减少 20%，来源准确率不下降”是待验证目标，不因此自动替换现有正式入口。

## 开发与许可证

Python 源码在 `src`，Obsidian 组件源码在 `tools/obsidian/graph/plugin`。仓库提供 Windows CI、合成示例、固定依赖和文件校验清单。命令见 [English README](README.md#development)，参与说明见 [CONTRIBUTING.md](CONTRIBUTING.md)，问题可提交至 [Issues](https://github.com/let778750-cpu/money-king/issues)。

自有代码采用 [AGPL-3.0](LICENSE)；既有 Obsidian 适配器保留 GPL-3.0，第三方组件保留原声明，见 [THIRD_PARTY.md](THIRD_PARTY.md)。不打包 Obsidian 应用。感谢 Python、Basic Memory、FastMCP、Obsidian 生态及 Harness 的公开设计资料；未复制 Harness 实现源码。
