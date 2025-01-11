import cfg
from pathlib import Path
import subprocess
import os,re,time,sys,json,shutil
from datetime import timedelta

from PySide6.QtWidgets import (QApplication, QMainWindow, QStatusBar, QLabel,
                             QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
                             QFileDialog, QComboBox, QLineEdit, QPlainTextEdit,QTextEdit,
                             QMessageBox, QSizePolicy,QSpacerItem)
from PySide6.QtCore import Qt, QThread, Signal,Slot,QTimer,QUrl
from PySide6.QtGui import QDesktopServices, QFont, QColor,QIcon,QCursor,QTextCursor
from urllib.parse import urlparse
import threading

import base64
import numpy as np
from pydub import AudioSegment
import socket
from googleapiclient.errors import HttpError
import google
from google.api_core.exceptions import ServerError,TooManyRequests,RetryError
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

safetySettings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT:HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH:HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT:HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT:HarmBlockThreshold.BLOCK_NONE
}



def sort_dict_by_number_keys_inplace(input_dict):
    sorted_items = sorted(input_dict.items(), key=lambda item: int(item[0]))
    sorted_dict = dict(sorted_items)
    return sorted_dict
'''
格式化毫秒或秒为符合srt格式的 2位小时:2位分:2位秒,3位毫秒 形式
print(ms_to_time_string(ms=12030))
-> 00:00:12,030
'''
def ms_to_time_string(*, ms=0, seconds=None):
    # 计算小时、分钟、秒和毫秒
    if seconds is None:
        td = timedelta(milliseconds=ms)
    else:
        td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000

    time_string = f"{hours}:{minutes}:{seconds},{milliseconds}"
    return format_time(time_string, ',')

# 将不规范的 时:分:秒,|.毫秒格式为  aa:bb:cc,ddd形式
# eg  001:01:2,4500  01:54,14 等做处理
def format_time(s_time="", separate=','):
    if not s_time.strip():
        return f'00:00:00{separate}000'
    hou, min, sec,ms = 0, 0, 0,0

    tmp = s_time.strip().split(':')
    if len(tmp) >= 3:
        hou,min,sec = tmp[-3].strip(),tmp[-2].strip(),tmp[-1].strip()
    elif len(tmp) == 2:
        min,sec = tmp[0].strip(),tmp[1].strip()
    elif len(tmp) == 1:
        sec = tmp[0].strip()
    
    if re.search(r',|\.', str(sec)):
        t = re.split(r',|\.', str(sec))
        sec = t[0].strip()
        ms=t[1].strip()
    else:
        ms = 0
    hou = f'{int(hou):02}'[-2:]
    min = f'{int(min):02}'[-2:]
    sec = f'{int(sec):02}'
    ms = f'{int(ms):03}'[-3:]
    return f"{hou}:{min}:{sec}{separate}{ms}"

# run ffprobe 获取视频元信息
def get_video_ms(mp4_file):
    try:

        p = subprocess.run(['ffprobe','-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', mp4_file],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,
                           encoding="utf-8",
                           text=True,
                           check=True,
                           creationflags=0 if sys.platform != 'win32' else subprocess.CREATE_NO_WINDOW)
        if p.stdout:
            out = json.loads(p.stdout)            
            if "streams" not in out or len(out["streams"]) < 1:
                raise Exception(f'ffprobe error:streams is 0')

            if "format" in out and out['format']['duration']:
                return int(float(out['format']['duration']) * 1000)
                        
        cfg.logger.error(str(p) + str(p.stderr))
        raise Exception(str(p.stderr))
    except subprocess.CalledProcessError as e:
        cfg.logger.exception(e)
        raise
    except Exception as e:
        raise




class TaskThread(QThread):

    task_finished = Signal(str)

    def __init__(self, video_path, api_key, model, parent=None):
        super().__init__(parent)
        self.video_paths = video_path
        self.api_key = api_key.split(',')

        self.model = model
        self.is_running = True


        self.error_exit=""

        cfg.logger.info(f'开始task线程:{video_path=},{api_key=}')
        
    def run(self):
        for i,file in enumerate(self.video_paths):
            file_name=Path(file).name
            try:
                audio_file=cfg.TEMP_DIR+f'/{file_name}-{time.time()}-16000.wav'
                command = [
                    "ffmpeg",
                    "-i",
                    file,
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-vn",
                    audio_file
                ]
                subprocess.run(command, check=True, capture_output=True,creationflags=0 if sys.platform != 'win32' else subprocess.CREATE_NO_WINDOW)
                # 模拟成功
                self._exec(file,audio_file)
                self.task_finished.emit(json.dumps({'type': 'ok', 'text': f'{file_name} 转写完成' }))
            except subprocess.CalledProcessError as e:
                print(f"Error running ffmpeg: {e}")
                err=e.stderr.decode()
                Path(file+'-error.txt').write_text(err,encoding='utf-8')
                raise Exception(err)

            except Exception as e:
                Path(file+'-error.txt').write_text(str(e),encoding='utf-8')
                cfg.logger.exception(f'转写{file_name}时出错', exc_info=True)
                self.task_finished.emit(json.dumps({'type': 'error', 'text': f'转写{file_name}时出错:{e}' }))
        self.stop()
        

    def _exec(self,file,audio_file):
        p=Path(file)
        
        self.task_finished.emit(json.dumps({'type': 'log', 'text': f'开始转写字幕 {p.name}' }))        
    
        seg_list=self.cut_audio(audio_file)
        if len(seg_list)<1:
            raise Exception(f'预先VAD切割失败: {file}')
        
        seg_list=[seg_list[i:i + 20] for i in  range(0, len(seg_list), 20)]
        generation_config = {
                  "temperature": 1,
                  "top_p": 0.95,
                  "top_k": 40,
                  "response_mime_type": "text/plain",
        }
        prompt= cfg.prompt_gemini
        result_srts=[]
        response=None
        for i,seg_group in enumerate(seg_list):
            api_key=self.api_key.pop(0)
            self.api_key.append(api_key)
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
              model_name=self.model,
              safety_settings=safetySettings
            )


            try:
                files=[]
                for f in seg_group:
                    files.append(
                        {
                            "mime_type": "audio/wav",
                            "data": Path(f['file']).read_bytes()
                        }

                    )
                chat_session = model.start_chat(
                    history=[
                        {
                            "role": "user",
                            "parts": files,
                        }
                    ]
                )
                cfg.logger.info(f'发送音频到Gemini:prompt={prompt}')
                response = chat_session.send_message(prompt,request_options={"timeout":600})
                cfg.logger.info(f'INFO[Gemini]{response.prompt_feedback.block_reason=},{response.candidates[0].finish_reason}')
                if response.prompt_feedback.block_reason>0:
                    raise Exception(self._get_error(response.prompt_feedback.block_reason, "forbid"))
                if len(response.candidates) > 0 and response.candidates[0].finish_reason >1:
                    raise Exception(self._get_error(response.candidates[0].finish_reason))
            except TooManyRequests as e:                               
                err=f'429 请求太快或超出Gemini每日限制'
                raise Exception(err)
            
            except (RetryError,socket.timeout,ServerError) as e:
                error='无法连接到Gemini,请尝试使用或更换代理'
                raise Exception(error)
            except google.api_core.exceptions.PermissionDenied:
                raise Exception(f'您无权访问所请求的资源或模型 ')
            except google.api_core.exceptions.ResourceExhausted:                
                raise Exception(f'您的配额已用尽。请稍等片刻，然后重试,若仍如此，请查看Google账号 ')
            except google.auth.exceptions.DefaultCredentialsError:                
                raise Exception(f'验证失败，可能 Gemini API Key 不正确 ')
            except google.api_core.exceptions.InvalidArgument:                
                raise Exception(f'文件过大或 Gemini API Key 不正确 ')
            except genai.types.BlockedPromptException as e:
                raise Exception(self._get_error(e.args[0].finish_reason))
            except genai.types.StopCandidateException as e:
                cfg.logger.exception(f'[Gemini]-3:{e=}', exc_info=True)
                if int(e.args[0].finish_reason>1):
                    raise Exception(self._get_error(e.args[0].finish_reason))
            except Exception as e:
                error = str(e)
                cfg.logger.exception(f'[Gemini]请求失败{e.__class__name}:{error=}', exc_info=True)
                if error.find('User location is not supported') > -1:
                    raise Exception("当前请求ip(或代理服务器)所在国家不在Gemini API允许范围")
                raise
            else:
                cfg.logger.info(f'gemini返回结果:{response.text=}')
                m=re.findall(r'<audio_text>(.*?)<\/audio_text>',response.text.strip(),re.I)
                if len(m)<1:
                    continue
                str_s=[]
                for j,f in enumerate(seg_group):
                    if j < len(m):
                        startraw=ms_to_time_string(ms=f['start_time'])
                        endraw=ms_to_time_string(ms=f['end_time'])
                        tmp_srt=f'{len(result_srts)+1}\n{startraw} --> {endraw}\n{m[j]}'
                        str_s.append(tmp_srt)
                        result_srts.append(tmp_srt)
                text="\n\n".join(str_s) 
                self.task_finished.emit(json.dumps({
                    'type': 'log', 
                    'text': f'{p.name} 进度：{round((i+1)*100/len(seg_list),2)}% \n{text}'
                }))


        # 获取到所有文字，开始处理为字幕

        if len(result_srts)<1:
            
            raise Exception(f'获取失败-3')
        

        str_srts="\n\n".join(result_srts)

        srt_name=p.parent.as_posix()+'/'+p.stem+'.srt'
        Path(srt_name).write_text(str_srts,encoding='utf-8')
        self.task_finished.emit(json.dumps({'type': 'log', 'text': f'\n【 已创建字幕: {srt_name} 】\n\n{str_srts}\n\n【 已创建字幕: {srt_name} 】\n'}))
        

    def _get_error(self, num=5, type='error'):
        REASON_CN = {
            2: "已达到请求中指定的最大令牌数量",
            3: "由于安全原因，候选响应内容被标记",
            4:"候选响应内容因背诵原因被标记",
            5:"原因不明",
            6:"候选回应内容因使用不支持的语言而被标记",
            7:"由于内容包含禁用术语，令牌生成停止",
            8:"令牌生成因可能包含违禁内容而停止",
            9: "令牌生成停止，因为内容可能包含敏感的个人身份信息",
            10: "模型生成的函数调用无效",
        }

        forbid_cn = {
            0: "安全原因被Gemini屏蔽",
            1: "被Gemini禁止翻译:出于安全考虑，提示已被屏蔽",
            2: "提示因未知原因被屏蔽了",
            3: "提示因术语屏蔽名单中包含的字词而被屏蔽",
            4: "系统屏蔽了此提示，因为其中包含禁止的内容。",
        }
        return REASON_CN[num] if type == 'error' else forbid_cn[num]
    
    
    # 根据 时间开始结束点，切割音频片段,并保存为wav到临时目录，记录每个wav的绝对路径到list，然后返回该list
    def cut_audio(self,audio_file):
        
        sampling_rate=16000
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import (
            VadOptions,
            get_speech_timestamps
        )

        def convert_to_milliseconds(timestamps):
            milliseconds_timestamps = []
            for timestamp in timestamps:
                milliseconds_timestamps.append(
                    {
                        "start": int(round(timestamp["start"] / sampling_rate * 1000)),
                        "end": int(round(timestamp["end"] / sampling_rate * 1000)),
                    }
                )

            return milliseconds_timestamps
        vad_p={
            "threshold":  0.5,
            "neg_threshold": 0.35,
            "min_speech_duration_ms":  0,
            "max_speech_duration_s":  float("inf"),
            "min_silence_duration_ms": 250,
            "speech_pad_ms": 200
        }
        speech_chunks=get_speech_timestamps(decode_audio(audio_file, sampling_rate=sampling_rate),vad_options=VadOptions(**vad_p))
        speech_chunks=convert_to_milliseconds(speech_chunks)
        
        dir_name = f"{cfg.TEMP_DIR}/{time.time()}"
        Path(dir_name).mkdir(parents=True, exist_ok=True)
        data=[]
        audio = AudioSegment.from_wav(audio_file)
        for it in speech_chunks:
            start_ms, end_ms=it['start'],it['end']
            chunk = audio[start_ms:end_ms]
            file_name=f"{dir_name}/{start_ms}_{end_ms}.wav"
            chunk.export(file_name, format="wav")
            data.append({"start_time":start_ms,"end_time":end_ms,"file":file_name})

        return data

    def stop(self):
        self.is_running = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PVT GeminiAI音视频转写v0.3   https://pyvideotrans.com")
        self.setMinimumSize(800, 600)

        # 设置窗口图标
        icon_path =  f"{cfg.ROOT_DIR}/static/icon.ico"
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.cache_cfg={}
        
        self.video_paths = []
        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)
        self.setup_ui()

    def setup_ui(self):
       
        # 视频选择按钮
        self.select_video_btn = QPushButton("点击或拖拽选择音视频文件",self)
        self.select_video_btn.setFixedHeight(200)
        self.select_video_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.select_video_btn.clicked.connect(self.select_video_file)
        self.set_hand_cursor(self.select_video_btn)
        self.layout.addWidget(self.select_video_btn)
    
        # 水平布局 1
        h_layout1 = QHBoxLayout()
        self.layout.addLayout(h_layout1)


       

        
        self.aitype = QComboBox(self)
        self.aitype.addItems(["GeminiAI Key"])
        
        h_layout1.addWidget(self.aitype)
        
        
        
        self.api_key = QLineEdit(self)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText('填写AI的API KEY,可填多个，英文逗号分隔')
        self.api_key.setToolTip('填写AI的API KEY,可填多个，英文逗号分隔')
        h_layout1.addWidget(self.api_key)

        h_layout1.addWidget(QLabel("选择模型", self))
        self.models = QComboBox(self)
        self.models.addItems(["gemini-2.0-flash-exp","gemini-1.5-flash"])
        h_layout1.addWidget(self.models)
        
        
        h_proxy=QHBoxLayout()
        self.proxy_label=QLabel('填写http代理地址和端口')
        self.proxy_input = QLineEdit(self)
        self.proxy_input.setPlaceholderText('如果计算机无法访问Gemini，请填写http代理')
        h_proxy.addWidget(self.proxy_label)
        h_proxy.addWidget(self.proxy_input)

        self.layout.addLayout(h_proxy)
    
        # 水平布局 2
        h_layout2 = QHBoxLayout()
        h_layout2.setAlignment(Qt.AlignCenter) #设置水平居中
        self.layout.addLayout(h_layout2)

        self.start_btn = QPushButton("开始", self)
        self.start_btn.setFixedHeight(35)
        self.start_btn.setMinimumWidth(200)
        self.start_btn.clicked.connect(self.start_task)
        self.set_hand_cursor(self.start_btn)
        h_layout2.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止", self)
        self.stop_btn.setFixedHeight(35)
        self.stop_btn.setFixedWidth(80)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_task)
        self.set_hand_cursor(self.stop_btn)

        self.opendir = QPushButton("打开结果文件夹", self)
        self.opendir.clicked.connect(self.opendir_fun)
        self.set_hand_cursor(self.opendir)
        h_layout2.addWidget(self.stop_btn)
        h_layout2.addWidget(self.opendir)

        #日志文本框
        self.logs = QTextEdit(self)
        self.logs.setReadOnly(True)
        self.logs.setPlaceholderText('等待开始执行任务')
        self.layout.addWidget(self.logs)
    
       # 底部状态栏
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        # 底部状态栏：左侧按钮
        self.doc_btn = QPushButton("查看使用文档",self)
        self.doc_btn.clicked.connect(self.open_doc_link)
        self.doc_btn.setStyleSheet("background-color: transparent; color: white;") # 设置背景透明，文字白色
        self.set_hand_cursor(self.doc_btn)
        self.status_bar.addWidget(self.doc_btn)


        # 底部状态栏：右侧按钮
        self.download_btn = QPushButton("下载新版本",self)
        self.download_btn.clicked.connect(self.open_download_link)
        self.set_hand_cursor(self.download_btn)
        self.download_btn.setStyleSheet("background-color: transparent; color: white;")  # 设置背景透明，文字白色
        self.status_bar.addPermanentWidget(self.download_btn)
        self.set_cache()
    
    def set_cache(self):
        if Path(cfg.ROOT_DIR+'/static/cfg.json').exists():
            self.cache_cfg=json.loads(Path(cfg.ROOT_DIR+'/static/cfg.json').read_text(encoding='utf-8'))

            self.proxy_input.setText(self.cache_cfg.get('proxy',''))
            self.api_key.setText(self.cache_cfg.get('api_key_gemini',''))
            if self.cache_cfg.get('last_opendir'):
                cfg.last_opendir=self.cache_cfg.get('last_opendir')

            
            

            
        
    def open_doc_link(self):
        """ 打开文档链接 """
        QDesktopServices.openUrl(QUrl("https://pyvideotrans.com/geminirecogn"))
        
    def open_download_link(self):
        """ 打开下载链接 """
        QDesktopServices.openUrl(QUrl("https://pyvideotrans.com/geminirecogn"))


    def opendir_fun(self):
        if self.video_paths and len(self.video_paths)>0:
            QDesktopServices.openUrl(QUrl(Path(self.video_paths[0]).parent.as_posix()))
            
    
    def set_hand_cursor(self, widget):
          """ 将控件的鼠标光标设置为手形 """
          widget.setCursor(QCursor(Qt.PointingHandCursor))
    
    def select_video_file(self):
        fnames, _ = QFileDialog.getOpenFileNames(self,
                                                     '选择一或多个文件',
                                                     cfg.last_opendir,
                                                     f'Files (*.mp4 *.avi *.mov *.mkv *.ts *.wav *.mp3 *.flac *.aac *.m4a)')
        mp4_list=[]                                             
        if len(fnames) < 1:
            return
        for (i, it) in enumerate(fnames):
            mp4_list.append(Path(it).as_posix())
        cfg.last_opendir = Path(mp4_list[0]).parent.resolve().as_posix()
        self.cache_cfg['last_opendir']=cfg.last_opendir
        
        self.video_paths=mp4_list
        self.select_video_btn.setText(f'选择了 {len(self.video_paths)} 个文件\n'+("\n".join([Path(n).name for n in mp4_list])) )

            
    def start_task(self):
        if len(self.video_paths)<1:
             QMessageBox.warning(self, "警告", "请先选择音视频文件")
             return
        if not self.api_key.text():
            QMessageBox.warning(self, "警告", "请先填写AI Key")
            return
            
        self.start_btn.setEnabled(False)
        self.start_btn.setText('任务执行中...')
        self.stop_btn.setEnabled(True)
        
        aitype=self.aitype.currentIndex()
        api_key=self.api_key.text()
        models=self.models.currentText()


        proxy=self.proxy_input.text().strip()
        self.cache_cfg['api_key_gemini']=api_key
        self.cache_cfg['models_gemini']=models
        self.cache_cfg['proxy']=proxy
        if proxy:
            os.environ['https_proxy']=proxy
            os.environ['http_proxy']=proxy

        
        
        Path(cfg.ROOT_DIR+"/static/cfg.json").write_text(json.dumps(self.cache_cfg),encoding='utf-8')
        
        self.task_thread = TaskThread(self.video_paths, api_key,models,self)
        self.task_thread.task_finished.connect(self.handle_task_result)
        self.task_thread.start()
        self.logs.clear()        
        

    @Slot(str)
    def handle_task_result(self, result):
        
        try:
            data = json.loads(result)
        except Exception as e:
            self.add_log_text(f"JSON解析失败:{result}", "error")
        else:
            log_type = data.get("type")
            log_text = data.get("text")
            
            if log_type == "error":
                self.add_log_text(log_text, "error")
                #self.start_btn.setEnabled(True)
                #self.start_btn.setText('任务出错了/重新开始')
                #self.stop_btn.setEnabled(False)
            elif log_type == "ok":
                self.add_log_text(f'<strong style="color:green;font-size:18px">{log_text}</strong><br><br>')
                self.start_btn.setText('任务完成/开始')
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
            elif self.task_thread and self.task_thread.isRunning():
                if log_type == "precent":
                    self.start_btn.setText(log_text)
                    self.add_log_text(log_text)
                else:
                    self.add_log_text(log_text)
    
    def add_log_text(self, text, log_type=None):
        """ 添加日志信息到文本框 """

        text=text.replace('\n','<br>')
        if log_type == "error":
            text=f"<span style='color: red;'>{text}</span><br>"
        else:        
            text=f"<span style='color: white;'>{text}</span><br>"
        self.logs.moveCursor(QTextCursor.End)
        self.logs.insertHtml(text)
        
    def stop_task(self):
        if self.task_thread and self.task_thread.isRunning():
            self.task_thread.stop()
        self.start_btn.setEnabled(True)
        self.start_btn.setText('重新开始')
        self.stop_btn.setEnabled(False)
        
    def closeEvent(self, event):
        """ 重写窗口关闭事件 """
        if hasattr(self, 'task_thread') and self.task_thread and self.task_thread.isRunning():
            self.task_thread.stop()
            self.hide()  # 隐藏窗口
            time.sleep(5)  # 5秒后关闭窗口
        event.accept()

    
if __name__ == "__main__":
    app = QApplication(sys.argv)
    import cfg.dark.darkstyle_rc
    with open('./static/style.qss', 'r', encoding='utf-8') as f:
        app.setStyleSheet(f.read())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
