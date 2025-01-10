
> 这是一个使用 Gemini AI 转录音频视频为 SRT 字幕的项目

Gemini AI 凭借强大的自然语言处理能力，可以快速、准确地将音视频内容转录为文字,并且提供了可观的每日免费额度，足以满足日常的音视频转录需求。

但是，直接将完整的音视频文件发送给 Gemini AI 虽然可以快速获得 SRT 格式的字幕，但时间轴往往不够精确。这主要是因为 Gemini AI 在处理长音频时，可能会出现时间轴偏移。

为了解决这个问题，从而诞生了本项目，主要自动完成以下操作：

1. **智能切片：** 利用 VAD（语音活动检测）模型，将音视频文件智能切分成小片段。
2. **逐片转录：** 将每个片段单独发送给 Gemini AI 进行转录。
3. **精准组装：** 将转录结果按时间顺序重新组装成一个完整的 SRT 字幕文件，确保时间轴的准确性。

**无需复杂的设置，只需简单操作，即可获得时间轴精确的 SRT 字幕！**

![image.png](https://pyvideotrans.com/img/20250110153031-0.webp)


## Windows 预打包版下载

win10/11 可直接下载预打包版本，解压后双击 app.exe 即可使用
  
  下载地址：

## MacOS上源码部署

> Maoc上使用 brew 安装 python3 和 ffmepg，如果你的Mac上不支持 `brew` 命令，需要安装 Homebrew
>使用该命令安装 Homebrew   `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
> 上述命令需要科学上网才可成功执行，如果失败，请使用下方命令
> `/bin/zsh -c "$(curl -fsSL https://gitee.com/cunkai/HomebrewCN/raw/master/Homebrew.sh)"`

1. 安装 python3.10+ , 如果已存在可跳过

    ```

    brew install python@3.10
    ln -s /opt/homebrew/opt/python@3.10/bin/python3 /opt/homebrew/bin/python3
    ln -s /opt/homebrew/opt/python@3.10/bin/pip3 /opt/homebrew/bin/pip3

    ```

2. 安装 ffmpeg和git  `brew install ffmpeg git`
3. 克隆仓库、安装依赖 

    ```
        git clone https://github.com/jianchang512/gemini-speech2srt
        cd gemini-speechsrt
        python3 -m venv venv
        . venv/bin/activate
        pip3 install -r requirements.txt       

    ```
4. 启动, 请确认当前在 `gemini-speechsrt` 目录下，先执行 `. venv/bin/activate` 激活虚拟环境， 再执行  `python3 app.py` 启动

## Linux上源码部署

1. 安装 python3.10+，如果已安装可跳过

    Debian系如 Ubuntu，执行 `apt install python3 ffmpeg python3-venv` 

    Fedora系如 Centos，执行 `yum install python3 ffmpeg python3-virtualenv`

2. 克隆仓库/安装依赖

    ```
    git clone https://github.com/jianchang512/gemini-speech2srt
    cd gemini-speech2srt
    python3 -m venv venv
    . venv/bin/activate
    pip3 install -r requirements.txt

    ```
3. 启动, 请确认当前在 `gemini-speechsrt` 目录下，先执行 `. venv/bin/activate` 激活虚拟环境， 再执行  `python3 app.py` 启动

## Windows下源码部署

1. 下载 python3.10 安装包，下载地址 https://www.python.org/ftp/python/3.10.10/python-3.10.10-amd64.exe
2. 双击打开下载的exe文件，注意选中**Add python.exe to PATH*t,否则无法直接使用 `python`命令
3. 从github下载**源码包**，解压后进入`requirements.txt` 所在文件夹内，文件夹地址栏输入`cmd`回车，在弹出的终端中输入命令 `python -m venv venv`,回车执行创建虚拟环境，继续输入`.\venv\scripts\activate`回车激活虚拟环境,以下操作都在该虚拟环境内
4. 安装依赖,  `pip install -r requirements.txt`
5. 启动，`python app.py`


## 网络代理

由于国内无法访问gemini，源码部署时，若未开启全局或设置系统代理，即便填写了代理地址和端口，可能仍无法访问，此时请打开依赖包 `site-packages\google\ai\generativelanguage_v1beta\services\generative_service\transports\grpc_asyncio.py`文件大约 226 行，在该行代码`("grpc.max_receive_message_length", -1),`下新增一行
`("grpc.http_proxy",os.environ.get('http_proxy') or os.environ.get('https_proxy'))`
再到 211 行下新增一行 `import os`

## 用到的部分开源项目

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper/)
- [QDarkStyleSheet](https://github.com/ColinDuquesnoy/QDarkStyleSheet)

> ("grpc.http_proxy",os.environ.get('http_proxy') or os.environ.get('https_proxy'))