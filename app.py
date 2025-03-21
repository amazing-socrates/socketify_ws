from socketify import App, OpCode
import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech.audio import PushAudioInputStream, AudioConfig
import json
from queue import Queue
import threading
import time
from dotenv import load_dotenv
import os
from speech_service import SpeechService
from speech_session import SpeechSession
import concurrent.futures

app = App()
speech_service = SpeechService()

result_queue = Queue(maxsize=10000)
ws_connections = set()

def send_results():
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=100)
    while True:
        futures = []
        # 非阻塞方式取出所有待发送的结果
        while not result_queue.empty():
            try:
                result = result_queue.get_nowait()
            except Exception as e:
                print(f"Result queue error: {e}")
                break
            message = json.dumps(result)
            # 将同一条消息广播给所有连接
            for ws in list(ws_connections):
                futures.append(executor.submit(ws.send, message, OpCode.TEXT))
        # 等待所有发送任务完成
        for future in futures:
            try:
                future.result(timeout=1)
            except Exception as e:
                print(f"Send error: {e}")
        time.sleep(0.1)

threading.Thread(target=send_results, daemon=True).start()

def ws_open(ws):
    print("WebSocket connected, starting recognition...")
    speech_service.start_recognition_async()
    ws_connections.add(ws)

def ws_message(ws, message, opcode):
    if opcode == OpCode.BINARY:
        try:
            json_length = int.from_bytes(message[:4], byteorder='big')
            json_data = message[4:4+json_length].decode('utf-8')
            audio_data = message[4+json_length:]

            if not hasattr(ws, "session"):
                ws.session = SpeechSession(ws, speech_service.recognizer, result_queue)
            session = ws.session

            session.update_session_info(json_data)
            session.bind_handlers()
            if audio_data:
                speech_service.write_audio(audio_data)
        except Exception as e:
            print(f"Error processing message: {e}")
    else:
        print("Received non-binary message, ignoring:", message)

def ws_close(ws, code, message):
    print("WebSocket closed")
    ws_connections.remove(ws)
    speech_service.stop_recognition()
    speech_service.audio_stream.close()
app.ws("/translate-stream", {
    "open": ws_open,
    "message": ws_message,
    "close": ws_close,
})

app.any("/", lambda res, req: res.end("Nothing to see here!"))
app.listen(3003, lambda config: print(f"Listening on port http://localhost:{config.port} now\n"))
app.run()