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

# Queue for recognition results with size limit
result_queue = Queue(maxsize=100)

# 用字典存储每个房间的 WebSocket 连接
room_connections = {}
# connections_lock = threading.Lock()

# # 用于节流的全局变量
# last_recognizing_time = 0
# throttle_interval = 0.5  # 每 0.5 秒最多处理一次 recognizing 事件

# Event handlers for speech recognition
def handle_recognizing(args, session_info):
    # global last_recognizing_time
    # current_time = time.time()
    # if current_time - last_recognizing_time < throttle_interval:
    #     return
    # last_recognizing_time = current_time

    try:
        translations = {lang: text for lang, text in args.result.translations.items()}
        result = {
            **session_info,
            "status": "recognizing",
            "translations": translations,
            "Message": translations.get("zh-Hans", "")
        }
        if not result_queue.full():
            result_queue.put(result)
        else:
            print("Result queue full, dropping result")
    except Exception as e:
        print(f"Error in handle_recognizing: {e}")

def handle_recognized(args, session_info):
    try:
        if hasattr(args.result, 'translations'):
            translations = {lang: text for lang, text in args.result.translations.items()}
            result = {
                **session_info,
                "status": "recognized",
                "translations": translations,
                "Message": translations.get("zh-Hans", "")
            }
            if not result_queue.full():
                result_queue.put(result)
            else:
                print("Result queue full, dropping result")
    except Exception as e:
        print(f"Error in handle_recognized: {e}")

def handle_session_stopped(args):
    result_queue.put({"status": "stopped"})

def handle_canceled(evt):
    print(f"Speech recognition canceled: {evt}")

# Background thread to send recognition results
# def send_results():
#          with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
#         while True:
#             if not result_queue.empty():
#                 result = result_queue.get()
#                 room_id = result.get("RoomId")
#                 message = json.dumps(result)
#                 if room_id in room_connections:
#                     ws_list = list(room_connections[room_id])
#                     futures = [executor.submit(ws.send, message, OpCode.TEXT) for ws in ws_list]
#                     for future in futures:
#                         future.result()
#             time.sleep(0.1)

def send_results():
    while True:
        if not result_queue.empty():
            result = result_queue.get()
            room_id = result.get("RoomId")
            message = json.dumps(result)
            if room_id in room_connections:
                ws_list = list(room_connections[room_id])
                for ws in ws_list:
                    try:
                        ws.send(json.dumps(result), OpCode.TEXT)
                    except Exception as e:
                        print(f"Error sending message to WebSocket: {e}")
        time.sleep(0.1)


# Start the background thread
threading.Thread(target=send_results, daemon=True).start()


# WebSocket event handlers
def ws_open(ws):
    print("WebSocket connected, starting recognition...")


def ws_message(ws, message, opcode):
    if opcode == OpCode.BINARY:
        try:

            # 共享的会话信息
            session_info = {
                "AppId": "Default_AppId",
                "RoomId": "Default_RoomId",
                "From": "default_user",
                "Binary": False
            }

            json_length = int.from_bytes(message[:4], byteorder='big')
            json_data = message[4:4+json_length].decode('utf-8')
            audio_data = message[4+json_length:]

            new_session_info = json.loads(json_data)
            session_info.update(new_session_info)
            room_id = session_info.get("RoomId")

            if room_id:
                if room_id not in room_connections:
                    room_connections[room_id] = set()
                room_connections[room_id].add(ws)

                # print("Session Info:", session_info)
            # 动态绑定事件处理器，携带会话信息
            recognizer.recognizing.disconnect_all()
            recognizer.recognized.disconnect_all()
            recognizer.recognizing.connect(lambda args: handle_recognizing(args, session_info))
            recognizer.recognized.connect(lambda args: handle_recognized(args, session_info))

            if audio_data:
                audio_stream.write(audio_data)
        except Exception as e:
            print(f"Error processing message: {e}")
    else:
        print("Received non-binary message, ignoring:", message)

def ws_close(ws, code, message):
    print("WebSocket closed")
    for room_id in room_connections:
        if room_id in room_connections:
            room_connections[room_id].discard(ws)
    # recognizer.stop_continuous_recognition_async().get()
    # audio_stream.close()

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