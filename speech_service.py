import os
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech.audio import PushAudioInputStream, AudioConfig


class SpeechService:
    def __init__(self):
        # 加载环境变量
        load_dotenv()
        self.subscription_key = os.getenv("SUBSCRIPTION_KEY")
        if not self.subscription_key:
            raise ValueError("SUBSCRIPTION_KEY 环境变量未设置")
        print("subscription_key:", self.subscription_key)

        self.region = "eastus"
        self.endpoint_string = (
            f"wss://{self.region}.stt.speech.microsoft.com/speech/universal/v2"
        )

        # 配置翻译识别
        self.translation_config = speechsdk.translation.SpeechTranslationConfig(
            subscription=self.subscription_key,
            endpoint=self.endpoint_string,
            target_languages=("de", "fr", "zh-Hans", "es", "en"),
            speech_recognition_language="en-US",
        )
        self.translation_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous"
        )
        self.translation_config.request_word_level_timestamps()

        self.auto_detect_config = (
            speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=["en-US", "zh-CN"]
            )
        )

        self.audio_stream = PushAudioInputStream(
            speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1
            )
        )
        self.audio_config = AudioConfig(stream=self.audio_stream)

        # 创建翻译识别器
        self.recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=self.translation_config,
            audio_config=self.audio_config,
            auto_detect_source_language_config=self.auto_detect_config,
        )
        self.recognizer.canceled.connect(
            lambda evt: print(
                f"Speech recognition canceled: {evt.reason}, details: {evt}"
            )
        )
        self.recognizer.session_stopped.connect(lambda evt: print("Session stopped"))

    def write_audio(self, data: bytes):
        """将音频数据写入音频流"""
        self.audio_stream.write(data)

    def start_recognition_async(self):
        """启动连续语音识别（异步）"""
        self.recognizer.start_continuous_recognition_async()

    def stop_recognition(self):
        """停止连续语音识别，并等待结果"""
        self.recognizer.stop_continuous_recognition_async().get()
