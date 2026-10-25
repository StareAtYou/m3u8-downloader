# M3U8 Downloader Pro

一个同时提供终端与桌面界面的可靠 HLS/M3U8 下载器。下载任务由独立本地服务统一管理，因此终端和 GUI 能同时查看、暂停、恢复与重试同一批任务。

## 主要能力

- 自动发现系统及环境变量中的**本机回环代理**，并行探测直连和代理，选择实际响应最快的下载通道；不会把请求交给非本机代理。
- 多任务、多片段并发下载；每个线程使用独立 HTTP 会话。
- 全局串行 FFmpeg 合并锁、每任务独立工作区与唯一临时输出文件，避免多任务同时合并时互相覆盖。
- 片段原子写入、断点续传与服务重启恢复；残留 `.part` 文件不会被当作完整片段。
- 支持普通媒体播放列表、主播放列表最高带宽变体、AES-128 密钥轮换和字节范围。
- 明确拒绝暂不支持的 SAMPLE-AES 与 EXT-X-MAP/fMP4，避免生成看似成功但不可播放的文件。
- 任务名会经过跨平台文件名清理，最终文件固定为 `<保存目录>/<任务名>/<任务名>.mp4`。
- 本地 IPC 使用随机认证密钥和 JSON 帧；任务列表只暴露脱敏 URL。

## 环境要求

- Python 3.11 或更高版本
- FFmpeg 可执行文件（默认命令名为 `ffmpeg`）

确认 FFmpeg 可用：

```bash
ffmpeg -version
```

创建环境并安装：

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[gui]"
```

开发与测试依赖：

```bash
python -m pip install -e ".[gui,dev]"
```

## 桌面界面

macOS 用户可以直接在 Finder 中双击项目根目录的 `start.command`。也可以在终端中一键启动：

```bash
./start.command
```

首次运行会自动检查 Python 3.11+、在项目目录创建 `.venv`，并安装桌面界面依赖；后续环境已就绪时会直接启动，不会重复安装。启动器不会修改系统 Python，也不会自动安装 Homebrew、Python 或 FFmpeg。未检测到 FFmpeg 时会显示警告并继续打开界面，可稍后在设置中填写 FFmpeg 的绝对路径。

如 macOS 阻止首次双击运行，可右键选择“打开”，或使用上面的终端命令。需要手工管理环境时，仍可按“环境要求”中的步骤安装，然后运行：

```bash
m3u8-gui
```

填写 M3U8 地址、任务名称和保存目录后选择“添加任务”。任务名称既是列表中的显示名，也是最终 MP4 文件名。界面支持批量添加、暂停、继续、取消、重试、打开输出目录、并发数与代理策略设置。关闭窗口不会终止正在下载的后台服务；系统托盘菜单可重新显示窗口、暂停全部任务或退出 GUI。

默认不覆盖同名文件。需要覆盖时，应在提交任务时明确启用覆盖选项；服务会先写入唯一临时 MP4，完成后再原子替换目标文件。

## 终端模式

GUI 与终端自动连接同一个本地服务，无需手工启动服务：

```bash
m3u8-client submit "https://example.com/master.m3u8" "课程第 01 集" --save-dir "$PWD/videos"
m3u8-client list
m3u8-client pause TASK_ID
m3u8-client resume TASK_ID
m3u8-client cancel TASK_ID
m3u8-client retry TASK_ID
```

覆盖已存在文件：

```bash
m3u8-client submit URL "任务名称" --save-dir ./videos --overwrite
```

交互模式和旧入口仍可使用：

```bash
m3u8-client interactive
python client.py
python server.py
```

## 代理策略

“自动选择”会收集操作系统代理以及 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`，但只接受 `localhost`、`127.0.0.0/8` 或 `::1` 上的 HTTP/HTTPS/SOCKS4/SOCKS5 代理。下载前会同时探测直连和可用本地代理，并选取最快成功路线。每次请求都禁用 `requests` 的隐式环境代理继承，防止绕过已选路线。

设置页也可强制仅直连，或配置显式本地代理。代理口令不会显示在任务事件或日志中。

## 暂停、恢复与数据目录

暂停发生在安全边界：正在写入的片段先完成原子替换；处于 FFmpeg 合并阶段的任务不会被中途暂停。服务退出时，活动任务会标记为“已中断”，重试后复用已经完整落盘的片段。

数据库、认证密钥和临时工作区使用操作系统标准用户目录（由 `platformdirs` 决定）：

- 数据目录：任务数据库与单实例锁
- 配置目录：权限受限的本地服务认证密钥
- 缓存目录：每任务独立片段工作区

取消成功或合并完成后会清理对应工作区。用户下载的视频及中间媒体格式已加入 `.gitignore`。

## 下载预构建版本

正式版本由 GitHub 托管 runner 自动构建，可在项目的 [Releases 页面](https://github.com/StareAtYou/m3u8-downloader/releases) 下载：

- Windows：`M3U8-Downloader-Pro-<版本>-Windows-<架构>.zip`
- macOS：`M3U8-Downloader-Pro-<版本>-macOS-<架构>.zip`
- Linux：`M3U8-Downloader-Pro-<版本>-Linux-<架构>.tar.gz`

每个压缩包都附带同名 `.sha256` 文件。macOS 或 Linux 可在下载目录验证：

```bash
shasum -a 256 -c M3U8-Downloader-Pro-*.sha256
```

Windows PowerShell 可查看摘要并与 `.sha256` 文件中的值比较：

```powershell
(Get-FileHash .\M3U8-Downloader-Pro-*.zip -Algorithm SHA256).Hash
```

程序目前未进行商业代码签名。macOS 首次启动可能需要在“系统设置 → 隐私与安全性”中确认；Windows 可能显示 SmartScreen 提示，请先核对 SHA-256 后再选择运行。Linux 包以 Ubuntu 22.04 为最低构建兼容基线。所有平台仍需自行安装 FFmpeg，或在设置中填写其可执行文件路径。

## 打包桌面应用

依赖版本由 `packaging/constraints.txt` 固定。安装后执行：

```bash
python -m pip install -c packaging/constraints.txt -e ".[gui,dev]"
python -m pip install -c packaging/constraints.txt "Nuitka==4.1.1"
PATH="$PWD/.venv/bin:$PATH" pyside6-deploy -c pysidedeploy.spec --no-install
```

macOS 产物位于 `dist/M3U8DownloaderPro.app`，默认未签名；首次启动可能需要在系统隐私与安全设置中确认。FFmpeg 作为外部运行时依赖，不会被打入应用包，请确保其位于 `PATH`，或在设置中填写绝对路径。

仅检查打包命令而不编译：

```bash
PATH="$PWD/.venv/bin:$PATH" pyside6-deploy -c pysidedeploy.spec --dry-run --no-install
```

推送与 `pyproject.toml` 版本一致的标签（例如 `v0.2.0`）时，GitHub Actions 会在 Windows、macOS 和 Ubuntu 22.04 上构建、执行成品 smoke test、生成 SHA-256，并创建或更新对应 Release。在 Actions 页手动运行 `Release` 工作流只生成临时 artifacts，不会创建正式 Release。

## 测试

```bash
python -m pytest -q
ruff check src tests server.py client.py
ruff format --check src tests server.py client.py
```

集成测试会用 FFmpeg 生成极小的本地 HLS 媒体，验证并发下载、串行合并、可播放输出、共享服务事件和带 `.part` 文件的重启恢复；找不到 FFmpeg 时只跳过真实媒体断言。

## 常见问题

- **提示无法连接后台服务**：确认本机 `127.0.0.1:61288` 未被其他程序占用。旧版默认使用 6000 端口，新版使用独立端口以便迁移期间共存。
- **FFmpeg 合并失败**：运行 `ffmpeg -version`，或在设置中填写正确的 FFmpeg 路径；同时确认输出目录有足够空间。
- **代理没有被使用**：自动模式只接受本机回环代理。确认代理软件正在监听其显示的本地端口。
- **文件已存在**：更换任务名，删除/移动旧文件，或明确启用覆盖。默认拒绝覆盖是为了保护已有视频。
- **任务重启后显示“已中断”**：这是安全恢复状态；选择“重试”即可复用已完成片段继续。
