import os
import numpy as np
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech.audio import PushAudioInputStream, AudioConfig
from silero_vad import load_silero_vad, get_speech_timestamps

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
        
        # 加载 Silero VAD 模型（全局只加载一次）
        self.vad_model = load_silero_vad()
        # 新增一个缓存，用来拼接短时音频数据
        self.audio_buffer = bytearray()

    def write_audio(self, data: bytes):
        """缓存约0.3秒的音频数据后，再进行 VAD 检测，检测到语音则写入音频流"""
        # 将接收到的音频数据追加到缓存中
        self.audio_buffer.extend(data)
        # 对于 16kHz、16位单声道，每秒采样数为16000，每个采样2字节，0.3秒对应 0.3*16000*2 = 9600 字节
        THRESHOLD_BYTES = 9600
        if len(self.audio_buffer) >= THRESHOLD_BYTES:
            # 拼接缓存数据并清空缓存
            buffer_data = bytes(self.audio_buffer)
            self.audio_buffer = bytearray()
            # 将二进制数据转换为 numpy 数组，格式为 int16
            audio_np = np.frombuffer(buffer_data, dtype=np.int16)
            # 使用 VAD 检测语音时间戳（单位秒）
            speech_timestamps = get_speech_timestamps(audio_np, self.vad_model, return_seconds=True)
            if speech_timestamps:
                self.audio_stream.write(buffer_data)
            else:
                print("VAD过滤：未检测到语音，丢弃缓存音频数据")

    def start_recognition_async(self):
        """启动连续语音识别（异步）"""
        self.recognizer.start_continuous_recognition_async()

    def stop_recognition(self):
        """停止连续语音识别，并等待结果"""
        self.recognizer.stop_continuous_recognition_async().get()
