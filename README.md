# video-text-extract

提取 B站 / 抖音视频文案，优先走字幕，没字幕时回退到 Whisper 语音识别。

## 安装

```bash
pip install -r scripts/requirements.txt
```

如果你是 Windows GPU 环境，`faster-whisper` 会优先使用系统 CUDA；没有完整 CUDA Toolkit 时，仓库也会通过 `requirements.txt` 安装对应的 NVIDIA 运行时轮子。

## 用法

```bash
python scripts/extract.py "https://www.bilibili.com/video/..."
python scripts/extract.py "https://v.douyin.com/xxxxx/"
python scripts/extract.py --json "https://v.douyin.com/xxxxx/"
```

## 常用参数

- `--model tiny|base|small|medium|large-v3|turbo`
- `--device auto|cpu|cuda`
- `--compute-type auto|float16|int8|int8_float16`
- `--beam-size 1`
- `--batch-size 8`
- `--hf-endpoint https://hf-mirror.com`
- `--proxy http://127.0.0.1:7890`

## 建议

- 有字幕时会直接用字幕，最快也最准。
- GPU 上优先用 `turbo` 或 `small`。
- Windows 上如果没有完整 CUDA Toolkit，也可以用 pip 的 NVIDIA 依赖。
- 如果 Hugging Face 访问慢，直接加 `--hf-endpoint https://hf-mirror.com`。
