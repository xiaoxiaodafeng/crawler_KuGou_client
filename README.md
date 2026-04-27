# 客户端酷狗爬虫

酷狗关键词搜索、音频解析、歌词保存脚本。

核心文件：

- `demo2.py`：命令行入口
- `kugou_client.py`：请求、签名、歌词抓取
- `kugou_models.py`：数据模型和结果整理
- `demo1.py`：`priv_url` 最小示例
- `demo2_logic.md`：流程说明

常用命令：

```powershell
python .\demo2.py 陈奕迅 --all-page --limit 10
```

```powershell
python .\demo2.py 陈奕迅 --all-page
```

默认输出结构：

```text
music_mp3/
  index.json
  <hash>/
    <hash>.mp3
    metadata.json
    lyrics.txt
```
