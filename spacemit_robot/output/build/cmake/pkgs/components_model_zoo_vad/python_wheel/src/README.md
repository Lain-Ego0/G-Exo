# VAD 组件

## 1. 项目简介

本组件为通用 VAD 封装，提供统一的 C++ 接口与 Python 绑定，支持本地语音活动检测，便于集成到 ASR、TTS、AI Agent 等应用中。当前已支持 Silero VAD（本地 ONNX），接口可扩展其他后端。功能特性如下：

| 类别     | 支持                                                                 |
| -------- | -------------------------------------------------------------------- |
| 部署方式 | **本地**（ONNX 推理）                                                |
| 检测方式 | 单帧检测 `Detect()`；流式检测 `Start()` + `SendAudioFrame()` + `Stop()` |
| 后端     | Silero VAD（当前）；接口可扩展 ENERGY、WEBRTC 等                     |
| 接口     | C++（`include/vad_service.h`）、Python（`spacemit_vad`）             |

支持的后端与配置：Silero（默认，16kHz，窗口 512 样本）；阈值 `trigger_threshold`/`stop_threshold`、平滑等详见 [API.md](API.md)。

## 2. 验证模型

按以下顺序完成依赖安装、模型准备与示例运行。

### 2.1. 安装依赖

- **编译环境**：CMake ≥ 3.16，C++17 编译器（GCC/Clang/MSVC）。
- **必选**：ONNX Runtime、libcurl（模型自动下载）。

```bash
# Linux 示例
sudo apt-get update
sudo apt-get install -y build-essential cmake libcurl4-openssl-dev
# ONNX Runtime: 从 https://github.com/microsoft/onnxruntime/releases 安装，或 SpacemiT 环境 apt install onnxruntime
```

**可选：**
- **Python 绑定**：`pip install pybind11`
- **流式示例（C++）**：需 audio 组件 + PortAudio，`apt install portaudio19-dev`，构建时 `cmake .. -DBUILD_STREAM_DEMO=ON`（需存在 `examples/stream_demo.cpp`）。

### 2.2. 下载模型

使用 Silero VAD 时需将模型放到默认路径 **`~/.cache/models/vad/silero/silero_vad.onnx`**；首次运行可自动下载，也可从镜像提前下载。

**模型源：**
- **进迭时空镜像（推荐）**：<https://archive.spacemit.com/spacemit-ai/model_zoo/vad/>  
  提供 VAD 模型压缩包，下载后解压到默认目录即可，例如：
  ```bash
  mkdir -p ~/.cache/models/vad
  cd ~/.cache/models/vad
  wget https://archive.spacemit.com/spacemit-ai/model_zoo/vad/silero.tar.gz
  tar -xzf silero.tar.gz
  ```
  解压后需得到 `silero/` 目录（内含 `silero_vad.onnx`），即默认路径 `~/.cache/models/vad/silero/`。
- **其他渠道**：从 Silero 官方或内部渠道获取模型，拷贝至上述目录。

### 2.3. 测试

本节提供示例程序的编译与运行方式，便于开发者快速验证效果。使用前需先按下列两种方式之一完成编译，再运行对应示例。

- **在 SDK 中验证**（2.3.1）：在已拉取的 SpacemiT Robot SDK 工程内用 `mm` 编译，产物部署到 `output/staging`，适合整机集成或与 ASR、TTS 等模块联调。
- **独立构建下验证**（2.3.2）：在 VAD 组件目录下用 CMake 本地编译，不依赖完整 SDK，适合快速体验或在不使用 repo 的环境下使用。

#### 2.3.1. 在 SDK 中验证

**编译**：本组件已纳入 SpacemiT Robot SDK 时，在 SDK 根目录下执行。SDK 拉取与初始化见 [SpacemiT Robot SDK Manifest](https://github.com/spacemit-robotics/manifest)（使用 repo 时需先完成 `repo init`、`repo sync` 等）。

```bash
source build/envsetup.sh
venv 3.13.12
cd components/model_zoo/vad
mm
```

构建完成后，除安装到 `output/staging` 外，wheel 包也会输出到 SDK 根目录下的 `output/dist/`。例如：

```bash
output/dist/spacemit_vad-1.0.0-xxx.whl
```

如需在当前虚拟环境中安装该 Python 包，可执行：

```bash
pip install output/dist/spacemit_vad-1.0.0-xxx.whl
```

**运行**：运行前在 SDK 根目录执行 `source build/envsetup.sh`，使 PATH 与库路径指向 `output/staging`，然后可执行：

**C++ 简单示例：**
```bash
vad_simple_demo
```

**Python 示例**（推荐先安装 wheel 包）：
```bash
pip install output/dist/spacemit_vad-1.0.0-xxx.whl
python vad/python/examples/vad_file_demo.py
```

**流式检测**（若 SDK 构建时已开启流式示例）：
```bash
vad_stream_demo
```

#### 2.3.2. 独立构建下验证

在 VAD 组件目录下完成编译后，运行下列示例。

**C++ 简单示例（默认构建即包含）：**
```bash
cd /path/to/vad
mkdir -p build && cd build
cmake ..
make -j$(nproc)
./bin/vad_simple_demo
```

**Python 示例：**
```bash
make -C build vad-install-python   # 或设置 PYTHONPATH
python python/examples/vad_file_demo.py
```

**流式检测（默认未开启）**：若存在 `examples/stream_demo.cpp` 且需测试 C++ 流式，需先安装 PortAudio（见 2.1），然后：
```bash
cd build
cmake .. -DBUILD_STREAM_DEMO=ON
make -j$(nproc)
./bin/vad_stream_demo
```

## 3. 应用开发

本章说明如何在自有工程中**集成 VAD 并调用 API**。环境与依赖见 [2.1](#21-安装依赖)，模型准备见 [2.2](#22-下载模型)，编译与运行示例见 [2.3](#23-测试)。

### 3.1. 构建与集成产物

无论通过 [2.3.1](#231-在-sdk-中验证)（SDK）或 [2.3.2](#232-独立构建下验证)（独立构建）哪种方式编译，完成后**应用开发所需**的库与头文件如下，集成时只需**包含头文件并链接对应库**：

| 产物 | 说明 |
| ---- | ---- |
| `include/vad_service.h` | **C++ API 头文件**，应用侧只需包含此头文件并链接下方库即可调用 |
| `output/dist/spacemit_vad-1.0.0-xxx.whl` | Python wheel 包，可直接 `pip install` 后在业务代码中 `import spacemit_vad` |
| `build/lib/libvad.a` | C++ 核心库，链接时使用 |
| `build/lib/libsilero_vad.a` | Silero 后端库，链接时使用 |
| `build/python/spacemit_vad/` | Python 包，`make vad-install-python` 安装后 `import spacemit_vad` |

示例可执行文件（非集成必需）：`build/bin/vad_simple_demo`、`build/bin/vad_stream_demo`（需 `-DBUILD_STREAM_DEMO=ON` 且存在流式示例源文件）。运行与验证步骤见 [2.3.1](#231-在-sdk-中验证) 或 [2.3.2](#232-独立构建下验证)。

### 3.2. API 使用

**C++**：头文件 `include/vad_service.h` 为唯一 API 入口，实现为 PIMPL。在业务代码中 `#include "vad_service.h"`，链接 `libvad.a` 与 `libsilero_vad.a`（及 ONNX Runtime、libcurl 等），即可使用。

```cpp
#include "vad_service.h"
using namespace SpacemiT;

auto config = VadConfig::Preset("silero").withTriggerThreshold(0.6f).withStopThreshold(0.35f);
auto engine = std::make_shared<VadEngine>(config);

auto result = engine->Detect(audio_frame, 16000);
if (result && result->IsSpeech()) std::cout << result->GetProbability() << std::endl;

engine->SetCallback(std::make_shared<MyCallback>());
engine->Start();
// ... SendAudioFrame() ...
engine->Stop();
```

**Python**：推荐优先安装构建出的 wheel 包后再使用，详见 `python/examples/` 与 [API.md](API.md)。

```bash
pip install output/dist/spacemit_vad-1.0.0-xxx.whl
python vad/python/examples/vad_file_demo.py
```

```python
import spacemit_vad
result = spacemit_vad.detect(audio_array)
# 或
engine = spacemit_vad.VadEngine()
result = engine.detect(audio_frame)
```

**CMake 集成**：将本组件作为子目录引入，并链接 `vad`、包含头文件路径即可。
```cmake
add_subdirectory(vad)
target_link_libraries(your_target PRIVATE vad)
target_include_directories(your_target PRIVATE ${VAD_SOURCE_DIR}/include)
```

### 3.3. 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `backend` | `VadBackendType` | `SILERO` | 后端类型 |
| `sample_rate` | `int` | `16000` | 采样率 |
| `window_size` | `int` | `512` | 窗口大小 (32ms @ 16kHz) |
| `trigger_threshold` | `float` | `0.5` | 语音开始阈值 |
| `stop_threshold` | `float` | `0.35` | 语音结束阈值 |
| `smoothing_window` | `int` | `10` | 平滑窗口大小 |

详见 [API.md](API.md)。

## 4. 常见问题

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 一直检测为静音 | 设备无输入、采样率不匹配或阈值过高 | 先用 `audio_demo record` 录音回放，再降低 `trigger_threshold` 验证。 |
| 背景噪声触发语音 | 阈值过低或环境噪声大 | 提高 `trigger_threshold`，增大平滑窗口，或在前级加入降噪。 |
| 语音结束太慢 | `stop_threshold` 或状态平滑导致拖尾 | 适当提高 `stop_threshold` 或缩短业务侧静音等待。 |
| barge-in 误触发 | TTS 回放泄漏到麦克风 | 使用外设硬件 AEC 或 `voice_chat_aec` 的 WebRTC AEC 模式。 |

## 5. 版本与发布

版本以本组件文档或仓库 tag 为准。

| 版本   | 说明 |
| ------ | ---- |
| 1.0.0  | 提供 C++ / Python 接口，支持 Silero VAD、单帧与流式检测。 |

## 6. 贡献方式

欢迎参与贡献：提交 Issue 反馈问题，或通过 Pull Request 提交代码。

- **编码规范**：C++ 代码遵循 [Google C++ 风格指南](https://google.github.io/styleguide/cppguide.html)。
- **提交前检查**：若仓库提供 lint 脚本，请在提交前运行并通过检查。

## 7. License

本组件源码文件头声明为 Apache-2.0，最终以本目录 `LICENSE` 文件为准。
