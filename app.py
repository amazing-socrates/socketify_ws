from socketify import App, OpCode
import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech.audio import PushAudioInputStream, AudioConfig
import json
from queue import Queue
import threading
import time
from dotenv import load_dotenv
import os
import concurrent.futures

# Initialize Socketify app
app = App()

# Load environment variables
load_dotenv()

# Get subscription key from environment
subscription_key = os.getenv("SUBSCRIPTION_KEY")
print("subscription_key:", subscription_key)
region = "eastus"
endpoint_string = f"wss://{region}.stt.speech.microsoft.com/speech/universal/v2"

# Configure speech translation
translation_config = speechsdk.translation.SpeechTranslationConfig(
    subscription=subscription_key,
    endpoint=endpoint_string,
    target_languages=("de", "fr", "zh-Hans", "es", "en"),
    speech_recognition_language="en-US",
)
translation_config.set_property(
    speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
    "Continuous"
)
translation_config.request_word_level_timestamps()

# Configure auto language detection
auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
    languages=["en-US", "zh-CN"]
)

# Set up audio stream with specific format
audio_stream = PushAudioInputStream(
    speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
)
audio_config = AudioConfig(stream=audio_stream)

# Initialize the recognizer
recognizer = speechsdk.translation.TranslationRecognizer(
    translation_config=translation_config,
    audio_config=audio_config,
    auto_detect_source_language_config=auto_detect_config,
)

# Queue for recognition results
result_queue = Queue()

# 用字典存储每个房间的 WebSocket 连接
room_connections = {}

# 共享的会话信息（线程安全的字典）
session_info = {
    "AppId": "Default_AppId",
    "RoomId": "Default_RoomId",
    "From": "default_user",
    "Binary": False
}

# Event handlers for speech recognition
def handle_recognizing(args):
    try:
        translations = {lang: text for lang, text in args.result.translations.items()}
        result = {
            **session_info,  # 使用当前的 session_info
            "status": "recognizing",
            "translations": translations,
            "Message": translations.get("zh-Hans", "")
        }
        result_queue.put(result)
    except Exception as e:
        print(f"Error in handle_recognizing: {e}")

def handle_recognized(args):
    try:
        if hasattr(args.result, 'translations'):
            translations = {lang: text for lang, text in args.result.translations.items()}
            result = {
                **session_info,  # 使用当前的 session_info
                "status": "recognized",
                "translations": translations,
                "Message": translations.get("zh-Hans", "")
            }
            result_queue.put(result)
    except Exception as e:
        print(f"Error in handle_recognized: {e}")

def handle_session_stopped(args):
    result_queue.put({"status": "stopped"})

def handle_canceled(evt):
    print(f"Speech recognition canceled: {evt}")

# Background thread to send recognition results
def send_results():
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        while True:
            if not result_queue.empty():
                result = result_queue.get()
                room_id = result.get("RoomId")
                message = json.dumps(result)
                if room_id in room_connections:
                    ws_list = list(room_connections[room_id])
                    # 检查 WebSocket 状态并发送
                    futures = []
                    for ws in ws_list:
                        if ws.ws and not ws.ws.closed:  # 确保连接有效
                            futures.append(executor.submit(ws.send, message, OpCode.TEXT))
                        else:
                            room_connections[room_id].discard(ws)  # 移除无效连接
                    # 等待发送完成
                    for future in futures:
                        try:
                            future.result(timeout=1)  # 设置超时，避免阻塞
                        except Exception as e:
                            print(f"Send error: {e}")
            time.sleep(0.05)  # 降低循环频率，减少负载

# Start the background thread
threading.Thread(target=send_results, daemon=True).start()

# WebSocket event handlers
def ws_open(ws):
    print("WebSocket connected, starting recognition...")
    # 只在连接建立时绑定事件处理器
    recognizer.recognizing.connect(handle_recognizing)
    recognizer.recognized.connect(handle_recognized)
    recognizer.session_stopped.connect(handle_session_stopped)
    recognizer.canceled.connect(handle_canceled)
    recognizer.start_continuous_recognition_async().get()

def ws_message(ws, message, opcode):
    if opcode == OpCode.BINARY:
        try:
            # 解析消息：前4字节为JSON长度
            json_length = int.from_bytes(message[:4], byteorder='big')
            json_data = message[4:4+json_length].decode('utf-8')
            audio_data = message[4+json_length:]

            # 更新全局 session_info
            new_session_info = json.loads(json_data)
            session_info.update(new_session_info)
            room_id = session_info.get("RoomId")

            # 将 WebSocket 连接加入对应房间
            if room_id:
                if room_id not in room_connections:
                    room_connections[room_id] = set()
                room_connections[room_id].add(ws)

            # 将音频数据写入流
            if audio_data:
                audio_stream.write(audio_data)

        except Exception as e:
            print(f"Error processing message: {e}")
    else:
        print("Received non-binary message, ignoring:", message)

def ws_close(ws, code, message):
    print("WebSocket closed")
    for room_id in room_connections:
        room_connections[room_id].discard(ws)
    recognizer.stop_continuous_recognition_async().get()
    audio_stream.close()

# Define WebSocket route
app.ws("/translate-stream", {
    "open": ws_open,
    "message": ws_message,
    "close": ws_close,
})

# Default route for non-WebSocket requests
app.any("/", lambda res, req: res.end("Nothing to see here!"))

# Start the server
app.listen(3003, lambda config: print(f"Listening on port http://localhost:{config.port} now\n"))
app.run()