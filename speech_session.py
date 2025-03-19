
import json
class SpeechSession:
    def __init__(self, ws, recognizer, result_queue):
        self.ws = ws
        self.recognizer = recognizer
        self.result_queue = result_queue
        self.session_info = {
            "AppId": "Default_AppId",
            "RoomId": "Default_RoomId",
            "From": "default_user",
            "Binary": False
        }

    def update_session_info(self, json_data):
        new_info = json.loads(json_data)
        self.session_info.update(new_info)

    def handle_recognizing(self, args):
        try:
            translations = {lang: text for lang, text in args.result.translations.items()}
            result = {
                **self.session_info,
                "status": "recognizing",
                "translations": translations,
                "Message": translations.get("zh-Hans", "")
            }
            if not self.result_queue.full():
                self.result_queue.put(result)
            else:
                print("Result queue full, dropping result")
        except Exception as e:
            print(f"Error in handle_recognizing: {e}")

    def handle_recognized(self, args):
        try:
            if hasattr(args.result, 'translations'):
                translations = {lang: text for lang, text in args.result.translations.items()}
                result = {
                    **self.session_info,
                    "status": "recognized",
                    "translations": translations,
                    "Message": translations.get("zh-Hans", "")
                }
                if not self.result_queue.full():
                    self.result_queue.put(result)
                else:
                    print("Result queue full, dropping result")
        except Exception as e:
            print(f"Error in handle_recognized: {e}")

    def bind_handlers(self):
        self.recognizer.recognizing.disconnect_all()
        self.recognizer.recognized.disconnect_all()
        self.recognizer.recognizing.connect(self.handle_recognizing)
        self.recognizer.recognized.connect(self.handle_recognized)