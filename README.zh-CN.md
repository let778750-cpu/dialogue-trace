# dialogue-trace

[English](README.md) · **简体中文** · [开始使用](#开始使用) · [使用案例](#一个研究问题怎样跨任务继续) · [下载](https://github.com/let778750-cpu/dialogue-trace/releases/tag/v0.8.0-preview.3)

dialogue-trace 是一个面向 Codex 的科研记忆工具。它把分散在不同任务中的讨论按研究问题组织起来，保留原始对话和结果依据，帮助你在继续工作时找回之前的判断、尚未解决的问题，以及下一步准备做什么。

它适合需要反复讨论、验证和修正方案的项目。例如，你今天在一个任务里设计实验，明天在另一个任务里发现条件发生了变化。将这些讨论放在同一条研究线中，就能沿着原话回顾方案为什么改变，而不必重新翻找每个聊天窗口。

项目以 **Codex Skill** 的形式安装。Skill 包含指导 Codex 记录和整理研究过程的操作说明，以及在本地保存数据的程序。基础功能可以直接在 Codex 中使用；如果你希望浏览下面这样的时间线，可以另外接入 Obsidian。

![在 Obsidian 中按顺序阅读研究讨论](assets/screenshots/timeline-light.jpg)

图中是实际 Obsidian 界面，内容来自随项目提供的合成温漂案例。蓝色卡片表示用户输入，紫色卡片表示 AI 回答；屏幕较窄时会改为单列。目前提供 Windows 上的 Codex 预览版，界面控件为中文，文档提供中英文版本。

## 开始使用

先确认你已经安装 Codex，并能在 PowerShell 中运行 `python --version`。初始化需要 Python 3.12 或更新版本，以及用于下载依赖的网络连接。Obsidian 可以稍后安装，日常使用不需要 Node.js。

### 1. 安装 Skill

在 Codex 中发送下面这段话：

```text
请使用 skill-installer，从 https://github.com/let778750-cpu/dialogue-trace
的仓库根目录安装 Skill，安装名称为 dialogue-trace。完成后告诉我安装目录。
```

也可以手动下载 [dialogue-trace-0.8.0-preview.3.zip](https://github.com/let778750-cpu/dialogue-trace/releases/download/v0.8.0-preview.3/dialogue-trace-0.8.0-preview.3.zip)，将解压得到的完整 `dialogue-trace` 文件夹放入 Codex 的 Skill 目录。默认位置是用户目录下的 `.codex\skills`；如果设置了 `CODEX_HOME`，则使用该目录下的 `skills` 文件夹。安装时需要保留所有文件，因为 `SKILL.md` 中的说明会调用包内程序。

### 2. 为研究项目初始化数据目录

在刚才安装的 `dialogue-trace` 文件夹中打开 PowerShell。下面以 `C:\Research\SensorDrift` 为项目目录，以 `C:\ResearchData\SensorDrift` 为数据目录。请先把路径换成自己的位置：项目目录需要已经存在，数据目录由初始化程序创建，并且必须位于 Skill 安装目录之外。

```powershell
.\scripts\install.ps1 -Workspace 'C:\Research\SensorDrift' -DataDir 'C:\ResearchData\SensorDrift'
.\scripts\memory.ps1 --root 'C:\ResearchData\SensorDrift' doctor
```

项目目录用于存放你正在研究的代码和资料。数据目录则保存原始记录、整理后的知识和本地运行环境，升级程序时会继续使用它。初始化会下载固定版本的 Python 和依赖，并为指定项目配置接入方式。

`doctor` 会列出数据位置、登记的项目目录、依赖版本和采集状态。请确认路径正确，并且依赖没有显示 `not_installed`。首次安装后看到 `hooks.state` 为 `not_observed`，表示尚未观察到宿主触发采集；这和安装失败是两回事，开始实际讨论后还需要核对记录是否进入系统。

### 3. 记录第一次讨论

在已登记的项目目录中打开一个新的 Codex 任务，发送下面的示例，并换成你自己的研究问题和数据路径：

```text
请使用 $dialogue-trace，数据目录是 C:\ResearchData\SensorDrift。
为“温升是否导致传感器漂移”建立一条研究线，记录这次讨论。
我们先梳理已有条件，结束时请留下待验证的问题和下一步实验。
```

Codex 应先确认当前研究线，再按协议记录和整理讨论。你可以接着补充实验条件、比较解释或讨论结果。结束前，让它说明哪些内容已经保存，并提供对应来源；这样也能检查这次讨论是否被正确记录。

以后继续这个问题时，明确说“继续温升与漂移这条研究线”，即可让 Codex 查找相关记录。如果宿主没有提供可读取的消息，系统应说明采集缺口，你可以要求 Codex 核对本任务的可用转录。安装 Skill 本身并不能保证每一轮对话都已自动归档。

需要处理下载中断、已有配置或升级问题时，请阅读[安装与维护说明](references/installation.zh-CN.md)。

## 在 Obsidian 中阅读时间线

完成上面的初始化后，可以在 Skill 目录运行：

```powershell
.\scripts\memory.ps1 --root 'C:\ResearchData\SensorDrift' attach-obsidian
```

这会将阅读组件安装到该数据实例的资料库中。另行安装 Obsidian 后，打开 `C:\ResearchData\SensorDrift\vault`，按应用提示确认信任并启用组件，再通过命令面板运行“打开研究时间线”。日常时间线可以独立使用；需要查看局部知识图时，再安装 Juggl 1.5.0。

时间线按来源顺序展示讨论，长回答可以展开或进入宽幅阅读。关键结果和研究断点保留来源入口，便于回到原话核对。命令输出与环境信息放在技术详情中，阅读研究过程时无需逐条翻过执行日志。

## 一个研究问题怎样跨任务继续

“项目”“研究线”和“任务”在这里有不同作用。项目确定研究范围，研究线围绕一个持续探索的问题，而任务是 Codex 中的一次对话。同一条研究线可以包含多个任务中的记录，一个任务也可能讨论几条研究线。

以温漂问题为例，你在第一个任务里提出“温升可能导致漂移”，随后补充“目前还没有统一预热时间”。这条新条件使原来的比较方案需要调整：应先确定热稳定条件，再比较漂移。几天后，你在另一个任务中继续这条研究线，就可以先找回这次修正，再决定还需要哪些重复试验。

如果话题转向一个需要单独推进的问题，例如测量设备的选型，可以让 Codex 建立新的研究线。已有消息按完整、连续的区间调整归属，原始来源会保留；同一份依据也可以被其他研究线引用。没有明确归属的内容留待确认，浏览某条研究线不会自动改变当前任务的绑定。

下面的研究断点把已知条件、尚未解决的问题和下一步放在一起，并提供原话入口。它描述的是研究工作进行到了哪里，不表示程序已经生成了可以恢复计算的检查点文件。

![研究断点中的已知条件、待解决问题和下一步](assets/screenshots/checkpoint.jpg)

需要排查某个结果时，可以进一步打开工具详情，分别查看调用参数、返回结果和来源信息。运行成功只说明程序完成了执行，结果是否支持研究结论仍需解释和验证。

![按需查看工具返回结果及其来源](assets/screenshots/tool-details.jpg)

### 试用截图中的案例

初始化完成后，在 Skill 目录执行以下命令。若前面使用了不同的数据目录，请同步修改 Python 的路径。演示目录必须是一个新位置，脚本会拒绝覆盖已有实例。

```powershell
& 'C:\ResearchData\SensorDrift\runtime\venv\Scripts\python.exe' .\scripts\showcase.py --root 'C:\ResearchData\DialogueTraceDemo' --with-obsidian
```

然后用 Obsidian 打开 `C:\ResearchData\DialogueTraceDemo\vault`，启用组件并打开研究时间线。该案例包含两个来源任务和一个研究断点，所有对话与工具数值都是合成的演示材料；脚本不会读取你的私人对话或执行科研实验。

### 视频演示

视频将在录制完成后补充。当前可按上面的步骤体验同一案例，录制和添加视频的方法见[演示说明](docs/DEMO.md)。

## 记录怎样保存，是否增加模型开销

公开消息和工具记录由本地脚本保存，去重、来源定位和索引也由程序完成，这部分不需要额外调用模型。判断一段讨论属于哪个研究问题、结果意味着什么，以及接下来应验证什么，则由当前 Codex 模型按批整理，因此仍会使用上下文和生成 token。

项目没有启动另一个模型持续读取全部对话。原始记录与整理结果分开保存，AI 归纳带有来源，后续可以纠正归属并保留修改历史。自动采集只针对已登记工作区内明确进入研究流程的任务，不会因为安装了 Skill 就扫描所有项目。

归档范围限于宿主提供的公开消息、公开过程说明和工具记录。项目不采集隐藏推理，也不复制自动压缩时的内部私有摘要；缺少的时间、token 数量或调用层级会保持未知。更多细节见[采集与轨迹说明](references/capture-and-trajectory.md)。

## 当前版本的验证情况

当前发布的是预览版。已完成 133 项 Python 测试、37 项 JavaScript 测试，以及独立安装、升级和部分实际 Obsidian 操作检查。完整结果与复现条件见[验证报告](VALIDATION.zh-CN.md)，后续提交的自动检查可在 [GitHub Actions](https://github.com/let778750-cpu/dialogue-trace/actions) 查看。

仍需验证的重点是两个同时活跃的 Codex 任务能否可靠地逐轮采集和续接，以及完整的界面性能与人工找回效率。现有测试不能证明它已经缩短了研究时间；正式替换日常入口前，还需要完成这些使用场景的验收。

## 参与开发

Python 后端位于 `src`，Obsidian 组件源码位于 `tools/obsidian/graph/plugin`。开发环境配置和检查命令见[贡献指南](CONTRIBUTING.md)，后端操作约定见[接口说明](references/research-api.md)。报告问题时，请在 [Issues](https://github.com/let778750-cpu/dialogue-trace/issues) 中提供版本、复现步骤和实际结果，使用合成材料说明问题即可。

## 许可证与致谢

本项目自有代码采用 [AGPL-3.0](LICENSE)。已有 Obsidian 适配器保留 GPL-3.0，第三方组件保留各自声明，具体范围见[第三方说明](THIRD_PARTY.md)。Obsidian 应用本身不包含在发行包内。

项目使用 Python、Basic Memory 和 FastMCP，并接入 Obsidian。工具详情的组织方式参考了 DeepSeek Harness Trajectory 的类型化记录设计，相关资料见[设计参考](references/capture-and-trajectory.md#借鉴-harness-的范围)。本项目没有复制 Harness 的实现代码，目前也没有提供 Harness 宿主适配。
