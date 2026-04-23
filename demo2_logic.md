# demo2 逻辑说明

这份文档只保留当前脚本最核心的流程和常用命令。

相关文件：

- [demo2.py](/e:/kugou/demo2.py)
- [kugou_client.py](/e:/kugou/kugou_client.py)
- [kugou_models.py](/e:/kugou/kugou_models.py)

## 整体流程

当前脚本的主链路是：

```text
keyword -> Web/H5 搜索 -> 提取歌曲 hash -> priv_url 解析播放地址 -> 获取歌词 -> 保存到本地
```

更具体一点：

1. 用关键词搜索歌曲  
   走的是 Web/H5 搜索接口，不是 PC 客户端私有签名搜索。

2. 从搜索结果里提取每首歌的 `hash`  
   `hash` 是后续拿音频和歌词的核心字段。

3. 调 `priv_url` 解析播放地址  
   拿到真正可播放的 `mp3` 地址。

4. 调歌词接口  
   先搜索歌词，再下载歌词内容；如果这条链路拿不到，再尝试歌曲详情歌词兜底。

5. 保存到本地目录  
   默认保存到 [music_mp3](/e:/kugou/music_mp3)。

## 保存结构

执行下载类命令后，默认目录结构是：

```text
music_mp3/
  index.json
  <hash>/
    <hash>.mp3
    metadata.json
    lyrics.txt
```

说明：

- `<hash>.mp3`：音频文件
- `metadata.json`：这首歌的重要信息
- `lyrics.txt`：歌词文本
- `index.json`：本次任务的总清单

## 各文件职责

### `demo2.py`

命令行入口，负责：

- 解析命令参数
- 调用客户端
- 保存文件
- 输出结果

### `kugou_client.py`

核心请求逻辑，负责：

- 搜索签名
- `priv_url` 签名
- 发请求
- 自动重试
- SSL fallback
- 歌词抓取

### `kugou_models.py`

数据整理层，负责：

- 参数模型
- 返回结构封装
- 提取 `hash`
- 提取播放地址
- 提取简化字段

## 常用命令

### 1. 只搜索

```powershell
python .\demo2.py 陈奕迅
```

作用：

- 只打印搜索结果
- 不下载音频
- 不保存文件

### 2. 搜索后解析当前页第一首

```powershell
python .\demo2.py 陈奕迅 --resolve-first
```

作用：

- 搜索关键词
- 解析当前页第一首歌的播放地址

### 3. 直接按 `hash` 解析音频

```powershell
python .\demo2.py --hash CBFA7DDE592B23322E21E4BDAA9BE9F9
```

作用：

- 不走搜索
- 直接解析指定歌曲的播放地址

### 4. 下载关键词结果

```powershell
python .\demo2.py 陈奕迅 --all-page
```

作用：

- 搜索所有页
- 逐首解析音频
- 逐首获取歌词
- 保存到 `music_mp3`

### 5. 先抓前 10 条测试

```powershell
python .\demo2.py 陈奕迅 --all-page --limit 10
```

作用：

- 只处理前 10 首
- 适合先验证目录、音频、歌词、JSON 是否正常

### 6. 全量抓取

```powershell
python .\demo2.py 陈奕迅 --all-page
```

作用：

- 抓取这个关键词的所有页
- 下载可用的音频
- 获取歌词
- 保存到 `music_mp3`

### 7. 指定下载目录

```powershell
python .\demo2.py 陈奕迅 --all-page --limit 10 --download-dir music_mp3
```

作用：

- 把结果保存到指定目录

### 8. 指定总清单输出路径

```powershell
python .\demo2.py 陈奕迅 --all-page --output .\music_mp3\index.json
```

作用：

- 手动指定总清单文件位置

### 9. 打印最终请求 URL

```powershell
python .\demo2.py 陈奕迅 --show-url
```

作用：

- 打印搜索请求 URL
- 方便调试

## 当前实现特点

### 搜索

- 关键词搜索走 Web/H5 接口
- 这条链路可以稳定复现

### 音频

- 音频地址来自 `priv_url`
- 不是所有歌曲都一定有可播地址

### 歌词

- 歌词保存为 `lyrics.txt`
- 已经做了去空行处理
- 现在是一行接一行，不会再插空白行

### 文件命名

- 目录名固定用 `hash`
- 元数据文件固定叫 `metadata.json`
- 歌词文件固定叫 `lyrics.txt`

## 一句话总结

当前脚本做的事情就是：

```text
搜歌 -> 拿 hash -> 解析 mp3 -> 抓歌词 -> 按 hash 保存到本地
```
