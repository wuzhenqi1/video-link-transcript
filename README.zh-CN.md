# Video Link Transcript

[English README](./README.md)

面向抖音和 B 站的视频转文本 skill。

它支持视频链接、链接清单、创作者主页、B 站 UID、抖音号等入口，先解析出公开视频链接，再把简体中文转写结果按创作者分目录保存到你指定的输出目录。

## 功能特点

- 支持抖音和 B 站
- 支持单条视频和批量视频
- 支持创作者级入口
- 支持抖音号通过本机 Edge 登录态解析主页
- 最终只输出 `.txt`
- 输出文本统一转为简体中文
- 默认按创作者分文件夹保存

## 支持的输入

- 单条 B 站或抖音视频链接
- 多条视频链接
- 每行一条链接的 TXT 文件
- 带 `url` 列的 CSV 文件，可选 `title` 列
- B 站创作者主页
- B 站 UID
- 抖音创作者主页
- 抖音 `sec_uid`
- 抖音号 / 搜索词
- 可反查创作者的抖音视频链接

## 输出规则

- 只保存 `.txt`
- 一个创作者对应一个文件夹
- 输出目录可通过 `--output-root` 指定
- 保存前统一转成简体中文
- 不生成 CSV 汇总
- 不生成 JSONL 索引
- 不生成额外报告目录

## 安装

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## 内置 Extractor

仓库里已经内置了 `scripts/extract.py`。

如果你想切换成别的 extractor，也可以在运行时手动传：

```powershell
--extractor "你的extract.py路径"
```

## GPU 要求

推荐使用 CUDA：

```powershell
--device cuda --compute-type float16 --batch-size 8
```

这个项目现在强制只走 GPU。只要 CUDA 不可用，脚本会直接退出，不会悄悄回退到 CPU。

请确保所用 Python 环境里已经安装带 CUDA 支持的 `faster-whisper` 和 `ctranslate2`。

## 用法

```powershell
python scripts/batch_extract_transcripts.py "<抖音视频链接>" --creator "creator-a" --device cuda --compute-type float16 --batch-size 8
```

```powershell
python scripts/batch_extract_transcripts.py "<抖音视频链接>" "<B站视频链接>" --creator "mixed-sample" --device cuda --compute-type float16 --batch-size 8
```

```powershell
python scripts/batch_extract_transcripts.py ".\\links.txt" --creator "creator-b" --device cuda --compute-type float16 --batch-size 8 --limit 5
```

```powershell
python scripts/batch_extract_transcripts.py --creator-id "<B站UID>" --platform bilibili --count 2 --device cuda --compute-type float16 --batch-size 8
```

```powershell
python scripts/batch_extract_transcripts.py --creator-id "<抖音号>" --platform douyin --count 2 --use-edge-profile --edge-profile-dir Default --show-browser --device cuda --compute-type float16 --batch-size 8
```

只采集链接：

```powershell
python scripts/collect_public_video_urls.py --creator-id "<抖音号>" --platform douyin --count 20 --use-edge-profile --edge-profile-dir Default --show-browser
```

## 说明

- 抖音号解析优先推荐使用已登录的 Edge 资料
- 如果 Edge 已登录，优先使用 `--use-edge-profile`
- 有些创作者主页未必能稳定列出公开视频
- 直接给视频链接依然是最稳的输入

## 限制

- 只适用于公开或可公开枚举的视频页面
- 不承诺支持私密、受保护或非公开内容
- 抖音和 B 站页面结构变化、风控或限流都可能影响结果
