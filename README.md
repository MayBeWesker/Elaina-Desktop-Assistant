# Elaina Desktop Assistant

**Elaina Desktop Assistant** 是一个面向 Windows 的语音桌面虚拟人助手，支持语音识别、云端或本地大语言模型、语音合成、人物表情与服装切换，以及按需读取当前窗口并给出建议。

本仓库是适合公开发布的精简版本。它不包含 API Key、`node_modules`、运行缓存、原始图片素材或任何本地大模型权重。

## 功能

- 桌面置顶虚拟人物，支持拖动、隐藏和系统托盘
- FunASR 中文语音识别与 Edge TTS 中文语音合成
- DeepSeek OpenAI 兼容 API 对话
- 可选 Ollama 本地模型，并可通过语音即时切换
- 日常服装、运动服装和基础表情切换
- 仅在用户明确提出查看请求时截取当前活动窗口
- VAD 语音打断：用户重新说话时停止上一轮播放
- 可见后端命令行，实时展示加载、识别、模型、TTS 与连接状态

## 工作流程

```text
麦克风 → VAD → FunASR → 云端 API / 本地 Ollama → 表情解析 → Edge TTS → 桌面人物
                              ↑
                   用户明确请求时附加当前窗口截图
```

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10（推荐）
- Node.js 18 或更高版本
- 麦克风与网络连接
- DeepSeek API Key
- 可选：Ollama 和支持视觉的本地模型

首次启动 FunASR 会从 ModelScope 下载语音识别模型。模型保存在用户的本地缓存中，不会写入 Git 仓库。

## 安装

### 1. 克隆项目

```powershell
git clone <your-repository-url> Elaina-Desktop-Assistant
cd Elaina-Desktop-Assistant
```

### 2. 创建 Python 环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果 PowerShell 禁止执行激活脚本，也可以不激活环境，启动器会自动使用 `.venv\Scripts\python.exe`。

### 3. 安装 Electron

```powershell
npm install
```

### 4. 配置 API Key

当前 PowerShell 会话：

```powershell
$env:DEEPSEEK_API_KEY="your-api-key"
```

长期保存到当前 Windows 用户：

```powershell
setx DEEPSEEK_API_KEY "your-api-key"
```

执行 `setx` 后需要重新打开命令行或重新登录。不要把真实密钥写入 `conf.yaml` 或提交到 Git。

### 5. 启动

双击：

```text
启动桌面助手.bat
```

启动器会打开两个窗口：桌面人物窗口，以及必须保留的后端状态命令行。ASR 与 TTS 首次加载可能需要几十秒；看到以下内容即表示后端就绪：

```text
Application startup complete.
Uvicorn running on http://0.0.0.0:1017
WebSocket /client-ws [accepted]
```

## 本地模型（可选）

仓库不包含本地模型。请自行安装 Ollama，并创建或拉取与 `config_alts/local_model.yaml` 中名称一致的模型：

```text
qwen35-2b-local:latest
```

如果使用其他模型，请同时修改 `MODEL` 和 `V_MODEL`。只有具备视觉能力的模型才能理解窗口截图。

## 语音命令

| 指令示例 | 效果 |
| --- | --- |
| `切换本地模型` | 切换到 Ollama 本地模型 |
| `切换云端模型` | 切回 `conf.yaml` 中的 API 模型 |
| `运动服装` | 切换为运动服半身形象 |
| `灵动助手` | 恢复默认日常形象和表情集 |
| `看看我正在做什么` | 截取当前活动窗口并进行说明 |
| `根据当前界面给我一些建议` | 根据当前窗口提供针对性建议 |

普通聊天不会自动读取屏幕或剪贴板。窗口截图仅在识别到明确请求时产生，并发送给配置的视觉模型。

## 配置

- `conf.yaml`：云端 API、视觉模型、ASR、TTS 与人物设置
- `config_alts/local_model.yaml`：本地 Ollama 配置
- `prompts/persona/elaina2.txt`：云端人格
- `prompts/persona/local_elaina.txt`：本地人格；发布版本与云端人格内容一致
- `model_dict.json`：当前桌面人物与表情映射

## 项目结构

```text
├─ asr/                 # FunASR 接口
├─ llm/                 # OpenAI 兼容 API 客户端
├─ module/              # 对话、打断、人物与音频调度
├─ prompts/             # 人格与工具提示
├─ static/
│  ├─ character/       # 实际使用的人物图片
│  ├─ desktop/         # Electron 桌面端逻辑
│  ├─ libs/            # 浏览器端 VAD/渲染依赖
│  └─ pictures/        # 应用图标
├─ tts/                 # Edge TTS 与音频传输
├─ conf.yaml
├─ main.js              # Electron 主进程
├─ server.py            # FastAPI/WebSocket 后端
└─ 启动桌面助手.bat
```



## License

本项目沿用仓库中的 [MIT License](LICENSE)。人物图片与第三方库可能拥有各自的许可要求；公开发布前请确认你拥有相关素材的分发权。
