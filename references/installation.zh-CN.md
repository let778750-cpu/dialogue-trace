# Windows 安装、升级与卸载

[English](installation.md) · [返回主页](../README.zh-CN.md)

完整仓库根目录就是 `research-memory` skill。程序目录与私有数据目录必须分开；不能只复制 `SKILL.md`。需有 Python 3.12+ 用于下载工具；初始化会将固定 CPython 3.12.11、锁定依赖及缓存放入私有实例。

```powershell
./scripts/install.ps1 -Workspace 'C:/Research/MyProject' -DataDir 'C:/ResearchMemory/MyArchive'
# 可选 Obsidian 界面：
./scripts/install.ps1 -Workspace 'C:/Research/MyProject' -DataDir 'C:/ResearchMemory/MyArchive' -WithObsidian
./scripts/memory.ps1 --root 'C:/ResearchMemory/MyArchive' doctor
```

上面路径只是示例。初始化只登记指定工作区；新实例必须由 skill 显式绑定研究任务，hooks 才会采集该任务。同目录普通任务不会因安装而自动开始记录。旧实例保留先前已启用的采集策略。

已有 MCP 与 hooks 设置先核对再修改；冲突时保留原值并报告位置。安装后重新打开任务，分别检查宿主工具加载、hooks 实际观测及转录补核；配置成功不等于每轮自动同步。

打开打印出的 Obsidian vault，由用户处理首次信任提示并启用组件。时间线不要求 Juggl；按需局部图需要 Juggl 1.5.0。Obsidian 应用不包含在发行包内。

## 升级

用完整新版本替换程序目录，私有数据目录保持。以相同工作区和数据目录运行 `install.ps1 -Upgrade`；需要更新界面时加 `-WithObsidian`。升级会备份元数据与插件状态；原始事件身份保持。

如果程序目录移动，旧的受管宿主路径可能被报告为冲突。先用旧安装的 `memory.ps1 --root <数据目录> uninstall` 移除精确匹配的受管入口，再初始化新位置；不能覆盖其他工具配置。已有非受管插件不会被强行替换。

## 卸载与恢复

运行 `memory.ps1 --root <数据目录> uninstall`，移除仍与该安装匹配的宿主入口，然后可自行删除下载的 skill。研究数据、本地运行环境、Obsidian 组件和阅读状态保留。

下载中断后用同一安装命令重试，会复用已下载内容。执行结果不确定时先核对原请求收据；不要换请求 ID 重跑实验。原始事件、来源哈希和规范知识为事实源，阅读与搜索投影可重建。
