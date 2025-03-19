from socketify import App, OpCode
import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech.audio import PushAudioInputStream, AudioConfig
import json
from queue import Queue
import threading
import time
from dotenv import load_dotenv
import os
from speech_session import SpeechSession

app = App()
load_dotenv()

subscription_key = os.getenv("SUBSCRIPTION_KEY")
print("subscription_key:", subscription_key)
region = "eastus"
endpoint_string = f"wss://{region}.stt.speech.microsoft.com/speech/universal/v2"

translation_config = speechsdk.translation.SpeechTranslationConfig(
    subscription=subscription_key,
    endpoint=endpoint_string,
    target_languages=("de", "fr", "zh-Hans", "es", "en"),
    speech_recognition_language="en-US",
)
translation_config.set_property(
    speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous"
)
translation_config.request_word_level_timestamps()

auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
    languages=["en-US", "zh-CN"]
)

audio_stream = PushAudioInputStream(
    speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
)
audio_config = AudioConfig(stream=audio_stream)

recognizer = speechsdk.translation.TranslationRecognizer(
    translation_config=translation_config,
    audio_config=audio_config,
    auto_detect_source_language_config=auto_detect_config,
)

recognizer.canceled.connect(lambda evt: print(f"Speech recognition canceled: {evt.reason}, details: {evt}"))
recognizer.session_stopped.connect(lambda evt: print("Session stopped"))

result_queue = Queue(maxsize=10000)
ws_connections = set()
def send_results():
    while True:
        for ws in list(ws_connections):
            if not result_queue.empty():
                result = result_queue.get()
                message = json.dumps(result)
                ws.send(message, OpCode.TEXT)
        time.sleep(0.1)

threading.Thread(target=send_results, daemon=True).start()

def ws_open(ws):
    print("WebSocket connected, starting recognition...")
    recognizer.start_continuous_recognition_async()
    ws_connections.add(ws)

def ws_message(ws, message, opcode):
    if opcode == OpCode.BINARY:
        try:
            json_length = int.from_bytes(message[:4], byteorder='big')
            json_data = message[4:4+json_length].decode('utf-8')
            audio_data = message[4+json_length:]

            if not hasattr(ws, 'session'):
                ws.session = SpeechSession(ws, recognizer, result_queue)
            session = ws.session

            session.update_session_info(json_data)
 
            session.bind_handlers()
            if audio_data:
                audio_stream.write(audio_data)
        except Exception as e:
            print(f"Error processing message: {e}")
    else:
        print("Received non-binary message, ignoring:", message)

def ws_close(ws, code, message):
    print("WebSocket closed")
    ws_connections.remove(ws)
    recognizer.stop_continuous_recognition_async().get()
    audio_stream.close()
app.ws("/translate-stream", {
    "open": ws_open,
    "message": ws_message,
    "close": ws_close,
})

app.any("/", lambda res, req: res.end("Nothing to see here!"))
app.listen(3003, lambda config: print(f"Listening on port http://localhost:{config.port} now\n"))
app.run()