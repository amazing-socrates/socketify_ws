from socketify import App, OpCode
import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech.audio import PushAudioInputStream, AudioConfig
import json
from queue import Queue
import threading
import time
from dotenv import load_dotenv
import os

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
    target_languages=("de", "fr", "zh-Hans","es","en"),
    speech_recognition_language="en-US",
)
translation_config.set_property(
    speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
    "Continuous"
)

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

# Event handlers for speech recognition
def handle_recognizing(args):
    print("handle_recognizing received:", args)
    try:
        translations = {lang: text for lang, text in args.result.translations.items()}
        print("Recognizing translations:", translations)
        result_queue.put({"status": "recognizing", "translations": translations})
    except Exception as e:
        print(f"Error in handle_recognizing: {e}")

def handle_recognized(args):
    print("handle_recognized received full args:", args)
    try:
        if hasattr(args.result, 'translations'):
            translations = {lang: text for lang, text in args.result.translations.items()}
            print("Recognized translations:", translations)
            result_queue.put({"status": "recognized", "translations": translations})
        else:
            print("No translations found in result")
            print("Result properties:", dir(args.result))
    except Exception as e:
        print(f"Error in handle_recognized: {e}")

def handle_session_stopped(args):
    print("Session stopped with args:", args)
    result_queue.put({"status": "stopped"})

def handle_canceled(evt):
    print(f"Speech recognition canceled: {evt}")
    print(f"Cancellation details: {evt.result.cancellation_details}")

# Connect event handlers to recognizer
recognizer.recognizing.connect(handle_recognizing)
recognizer.recognized.connect(handle_recognized)
recognizer.session_stopped.connect(handle_session_stopped)
recognizer.canceled.connect(handle_canceled)

# Set to store active WebSocket connections
ws_connections = set()

# Background thread to send recognition results
def send_results():
    while True:
        for ws in list(ws_connections):
            if not result_queue.empty():
                result = result_queue.get()
                print("Sending result:", result)
                ws.send(json.dumps(result), OpCode.TEXT)
        time.sleep(0.1)

# Start the background thread
threading.Thread(target=send_results, daemon=True).start()

# WebSocket event handlers
def ws_open(ws):
    print("WebSocket connected, starting recognition...")
    ws_connections.add(ws)
    # Additional configuration for debugging and timeouts
    translation_config.set_property(
        speechsdk.PropertyId.Speech_LogFilename, "speech_log.txt"
    )
    translation_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "5000"
    )
    recognizer.start_continuous_recognition_async().get()
    print("Recognition started")

def ws_message(ws, message, opcode):
    if opcode == OpCode.BINARY:
        audio_stream.write(message)
        # Uncomment to debug received audio data
        # print("Received audio data:", message)
    else:
        print("Received non-binary message:", message)

def ws_close(ws, code, message):
    print("WebSocket closed")
    ws_connections.remove(ws)
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