import os
import re
import shutil
import atexit
import json
import asyncio
import threading
from typing import List, Dict, Any

# Import FunASR before FastAPI/Uvicorn and other framework modules on Windows.
# In affected Windows TxF sessions, delaying FunASR's package discovery until
# later imports or the event loop can produce WinError 6714.
if os.name == "nt":
    from asr.fun_asr import VoiceRecognition as _WindowsFunASRPreload  # noqa: F401

import yaml
import numpy as np
import chardet
from loguru import logger

_script_dir = os.path.dirname(os.path.abspath(__file__))
from fastapi import FastAPI, WebSocket, APIRouter
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect
from module.openllm_vtuber_main import OpenLLMVTuberMain
from module.live2d_model import Live2dModel
from tts.stream_audio import AudioPayloadPreparer
import argparse


class WebSocketServer:
    """
    WebSocketServer initializes a FastAPI application with WebSocket endpoints and a broadcast endpoint.

    Attributes:
        app (FastAPI): FastAPI application instance.
        router (APIRouter): APIRouter instance for routing.
        connected_clients (List[WebSocket]): List of connected WebSocket clients for "/client-ws".
        open_llm_vtuber_main_config (dict): Configuration dictionary.
    """

    def __init__(self, open_llm_vtuber_main_config: Dict | None = None, web=False):
        """
        Initializes the WebSocketServer with the given configuration.

        Parameters:
            open_llm_vtuber_main_config (dict): Configuration dictionary.
            web (bool): Whether to mount static files.
        """
        self.app = FastAPI()
        self.router = APIRouter()
        self.connected_clients: List[WebSocket] = []
        # FunASR/numba module discovery is not safe to run concurrently.
        self._component_init_lock = threading.Lock()
        self.open_llm_vtuber_main_config = open_llm_vtuber_main_config

        # Initialize model manager  
        self.preload_models = self.open_llm_vtuber_main_config.get("SERVER", {}).get(
            "PRELOAD_MODELS", False
        )
        
        if self.preload_models:
            logger.info("Preloading ASR and TTS models...")
            logger.info(
                "Using: " + str(self.open_llm_vtuber_main_config.get("ASR_MODEL"))
            )
            logger.info(
                "Using: " + str(self.open_llm_vtuber_main_config.get("TTS_MODEL"))
            )

            self.model_manager = ModelManager(self.open_llm_vtuber_main_config)
            self.model_manager.initialize_models()

        self._setup_routes()
        if web:
            self._mount_static_files()
        self.app.include_router(self.router)
        

    async def _handle_config_switch(
        self, websocket: WebSocket, config_file: str
    ) -> tuple[Live2dModel, OpenLLMVTuberMain] | None:
        new_config = self._load_config_from_file(config_file)
        if new_config:
            try:
                if self.preload_models:
                    self.model_manager.update_models(new_config)

                self.open_llm_vtuber_main_config.update(new_config)

                loop = asyncio.get_event_loop()
                l2d, open_llm_vtuber, _ = self._initialize_components(websocket, loop)

                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "config-switched",
                            "message": f"Switched to config: {config_file}",
                        }
                    )
                )
                await websocket.send_text(
                    json.dumps({"type": "set-model", "text": l2d.model_info})
                )
                logger.info(f"Configuration switched to {config_file}")

                return l2d, open_llm_vtuber

            except Exception as e:
                logger.error(f"Error switching configuration: {e}")
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": f"Error switching configuration: {str(e)}",
                        }
                    )
                )
                return None
        return None

    def _initialize_components(
        self, websocket: WebSocket, loop
    ) -> tuple[Live2dModel, OpenLLMVTuberMain, AudioPayloadPreparer]:
        """Initialize or reinitialize components with current configuration."""
        with self._component_init_lock:
            return self._initialize_components_unlocked(websocket, loop)

    def _initialize_components_unlocked(
        self, websocket: WebSocket, loop
    ) -> tuple[Live2dModel, OpenLLMVTuberMain, AudioPayloadPreparer]:
        """Perform component initialization while holding the server lock."""
        l2d = Live2dModel(self.open_llm_vtuber_main_config["LIVE2D_MODEL"])

        # Use cached models if available
        custom_asr = (
            self.model_manager.cache.get("asr") if self.preload_models else None
        )
        custom_tts = (
            self.model_manager.cache.get("tts") if self.preload_models else None
        )

        open_llm_vtuber = OpenLLMVTuberMain(
            self.open_llm_vtuber_main_config,
            custom_asr=custom_asr,
            custom_tts=custom_tts,
            loop = loop
        )

        audio_preparer = AudioPayloadPreparer()

        # Set up the audio playback function
        def _websocket_audio_handler(
            sentence: str | None, 
            filepath: str | None,
            instrument_filepath: str | None = None
        ) -> None:
            if filepath is None:
                logger.info("No audio to be streamed. Response is empty.")
                asyncio.run_coroutine_threadsafe(
                    websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "TTS 生成失败，请检查网络或更换 TTS 引擎",
                    })),
                    loop,
                )
                return

            if sentence is None:
                sentence = ""

            logger.info(f"Playing {filepath}...")
            display_sentence = l2d.remove_emotion_keywords(sentence)
            payload, duration = audio_preparer.prepare_audio_payload(
                audio_path=filepath,
                instrument_path=instrument_filepath,
                display_text=display_sentence,
                expression_list=l2d.extract_emotion(sentence),
            )
            logger.info("Payload prepared")

            async def _send_audio():
                await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(duration)

            asyncio.run_coroutine_threadsafe(_send_audio(), loop)

            logger.info("Audio played")

        open_llm_vtuber.set_audio_output_func(
            lambda sentence, filepath, instrument_filepath=None: _websocket_audio_handler(
                sentence, filepath, instrument_filepath
            )
        )

        def _websocket_character_handler(mode: dict) -> None:
            asyncio.run_coroutine_threadsafe(
                websocket.send_text(json.dumps({"type": "character-mode", **mode})),
                loop,
            )

        open_llm_vtuber.set_character_output_func(_websocket_character_handler)
        return l2d, open_llm_vtuber, audio_preparer

    def _setup_routes(self):
        """Sets up the WebSocket and broadcast routes."""

        # the connection between this server and the frontend client
        # The version 2 of the client-ws. Introduces breaking changes.
        # This route will initiate its own main.py instance and conversation loop
        @self.app.get("/")
        async def redirect_root():
            return RedirectResponse(url="/web.html")

        @self.app.websocket("/client-ws")
        async def websocket_endpoint(websocket: WebSocket):
            loop = asyncio.get_event_loop()
            await websocket.accept()
            await websocket.send_text(
                json.dumps({"type": "full-text", "text": "Connection established"})
            )

            self.connected_clients.append(websocket)
            print("\n[WebSocket] Client connected! Waiting for audio...")

            await websocket.send_text(
                json.dumps({"type": "full-text", "text": "正在加载 ASR / TTS 模型…"})
            )
            try:
                # FunASR's Windows module/model discovery can fail with
                # WinError 6714 when it runs inside asyncio's worker thread.
                # Initialize on the server thread on Windows; other platforms
                # retain the non-blocking worker-thread path.
                if os.name == "nt":
                    l2d, open_llm_vtuber, _ = self._initialize_components(
                        websocket, loop
                    )
                else:
                    l2d, open_llm_vtuber, _ = await asyncio.to_thread(
                        self._initialize_components, websocket, loop
                    )
            except Exception as exc:
                # Do not use logger.exception here on Windows: Loguru's rich
                # traceback formatter re-opens source files and can mask the
                # original error with WinError 6714 in a broken TxF context.
                logger.error(
                    "Failed to initialize ASR/TTS components: "
                    f"{type(exc).__name__}: {exc}"
                )
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "message": f"ASR / TTS 初始化失败：{exc}",
                    })
                )
                await websocket.close(code=1011)
                return

            await websocket.send_text(
                json.dumps({"type": "set-model", "text": l2d.model_info})
            )
            print("Model set")
            received_data_buffer = np.array([])
            # start mic
            await websocket.send_text(
                json.dumps({"type": "control", "text": "start-mic"})
            )
            await websocket.send_text(
                json.dumps({"type": "full-text", "text": "语音模型已就绪，正在监听…"})
            )

            conversation_task = None

            try:
                while True:
                    print(".", end="", flush=True)
                    message = await websocket.receive_text()
                    data = json.loads(message)
                    # print(f"\033\n Received ws req: {data.get('type')}\033[0m\n")

                    if data.get("type") == "interrupt-signal":
                        print("Start receiving audio data from front end.")
                        if conversation_task is not None:
                            print(
                                "\033[91mLLM hadn't finish itself. Interrupting it...",
                                "heard response: \n",
                                data.get("text"),
                                "\033[0m\n",
                            )
                            open_llm_vtuber.interrupt(data.get("text"))
                            # If generation already ended and only browser audio
                            # was playing, no worker remains to clear the flag.
                            if conversation_task.done():
                                open_llm_vtuber.interrupt_manager.interrupt_post_processing()

                    elif data.get("type") == "mic-audio-data":
                        audio_chunk = np.array(list(data.get("audio").values()), dtype=np.float32)
                        received_data_buffer = np.append(received_data_buffer, audio_chunk)
                        if data.get("clipboardData"):
                            clipboard_data = data.get("clipboardData")
                        if len(received_data_buffer) == len(audio_chunk):
                            print(f"\n[Audio] First chunk: {len(audio_chunk)} samples, max={audio_chunk.max():.4f}")
                        print("*", end="", flush=True)

                    elif (
                        data.get("type") == "mic-audio-end"
                        or data.get("type") == "text-input"
                    ):
                        print(f"\n[Audio] Received mic-audio-end. Total buffer: {len(received_data_buffer)} samples ({len(received_data_buffer)/16000:.1f}s)")
                        await websocket.send_text(
                            json.dumps({"type": "full-text", "text": "Thinking..."})
                        )
                        if data.get("type") == "text-input":
                            user_input = data.get("text")
                        else:
                            user_input: np.ndarray | str = received_data_buffer
                            if len(user_input) == 0:
                                print("[Audio] WARNING: Empty audio buffer!")
                                received_data_buffer = np.array([])
                                continue

                        received_data_buffer = np.array([])

                        # A new utterance starts a new generation. Let an active
                        # interrupted worker finish first; it owns resetting the
                        # shared interruption flag after all producer/TTS/audio
                        # threads have stopped. A completed old task may have
                        # been interrupted only to stop browser playback, in
                        # which case reset the flag here.
                        if conversation_task is not None and not conversation_task.done():
                            print("[Interrupt] Waiting for the old conversation to stop...")
                            try:
                                await conversation_task
                            except (InterruptedError, asyncio.CancelledError):
                                pass
                        if open_llm_vtuber.interrupt_manager.in_interrupt():
                            open_llm_vtuber.interrupt_manager.interrupt_post_processing()
                            print("[Interrupt] Ready for the new conversation.")

                        async def _run_conversation():
                            try:
                                await websocket.send_text(
                                    json.dumps({
                                        "type": "control",
                                        "text": "conversation-chain-start",
                                    })
                                )
                                await asyncio.to_thread(
                                    open_llm_vtuber.conversation_chain,
                                    user_input=user_input,
                                    clipboard_data=clipboard_data if "clipboard_data" in locals() else None
                                )
                                await websocket.send_text(
                                    json.dumps({
                                        "type": "control",
                                        "text": "conversation-chain-end",
                                    })
                                )
                                print("One Conversation Loop Completed")
                            except asyncio.CancelledError:
                                print("Conversation task was cancelled.")
                            except InterruptedError as e:
                                print(f"Conversation was interrupted. {e}")

                        conversation_task = asyncio.create_task(_run_conversation())
                    elif data.get("type") == "fetch-configs":
                        config_files = self._scan_config_alts_directory()
                        await websocket.send_text(
                            json.dumps({"type": "config-files", "files": config_files})
                        )
                    elif data.get("type") == "switch-config":
                        config_file = data.get("file")
                        if config_file:
                            result = await self._handle_config_switch(
                                websocket, config_file
                            )
                            if result:
                                l2d, open_llm_vtuber = result

                    elif data.get("type") == "fetch-backgrounds":
                        bg_files = self._scan_bg_directory()
                        await websocket.send_text(
                            json.dumps({"type": "background-files", "files": bg_files})
                        )
                    else:
                        print("Unknown data type received.")

            except WebSocketDisconnect:
                print("Client disconnected")
                self.connected_clients.remove(websocket)
                open_llm_vtuber = None

    def _scan_config_alts_directory(self) -> List[str]:
        config_files = ["conf.yaml"]  # default config file
        config_alts_dir = self.open_llm_vtuber_main_config.get(
            "CONFIG_ALTS_DIR", "config_alts"
        )
        for root, _, files in os.walk(config_alts_dir):
            for file in files:
                if file.endswith(".yaml"):
                    config_files.append(file)
        return config_files

    def _load_config_from_file(self, filename: str) -> Dict:
        """
        Load configuration from a YAML file with robust encoding handling.

        Args:
            filename: Name of the config file

        Returns:
            Dict: Loaded configuration or None if loading fails
        """
        if filename == "conf.yaml":
            return load_config_with_env("conf.yaml")

        config_alts_dir = self.open_llm_vtuber_main_config.get(
            "CONFIG_ALTS_DIR", "config_alts"
        )
        file_path = os.path.join(config_alts_dir, filename)

        if not os.path.exists(file_path):
            logger.error(f"Config file not found: {file_path}")
            return None

        # Try common encodings first
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "ascii"]
        content = None

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as file:
                    content = file.read()
                    break
            except UnicodeDecodeError:
                continue

        if content is None:
            # Try detecting encoding as last resort
            try:
                with open(file_path, "rb") as file:
                    raw_data = file.read()
                detected = chardet.detect(raw_data)
                if detected["encoding"]:
                    content = raw_data.decode(detected["encoding"])
            except Exception as e:
                logger.error(
                    f"Error detecting encoding for config file {file_path}: {e}"
                )
                return None

        try:
            return yaml.safe_load(content)
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML from {file_path}: {e}")
            return None

    def _scan_bg_directory(self) -> List[str]:
        bg_files = []
        bg_dir = os.path.join("static", "bg")
        for root, _, files in os.walk(bg_dir):
            for file in files:
                if file.endswith((".jpg", ".jpeg", ".png", ".gif")):
                    bg_files.append(file)
        return bg_files

    def _mount_static_files(self):
        """Mounts static file directories."""
        self.app.mount("/", StaticFiles(directory="./static", html=True), name="static")
        pass

    # def run(self, host: str = "127.0.0.1", port: int = 8000, log_level: str = "info"):
    #     """Runs the FastAPI application using Uvicorn."""
    #     import uvicorn

    #     uvicorn.run(self.app, host=host, port=port, log_level=log_level)

    def run(self, host: str = "127.0.0.1", port: int = 8000, log_level: str = "info"):
        """Runs the FastAPI application using Uvicorn."""
        import uvicorn

        uvicorn.run(self.app, host=host, port=port, log_level=log_level)

    @staticmethod
    def clean_cache():
        """Clean the cache directory by removing and recreating it."""
        cache_dir = "./cache"
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            os.makedirs(cache_dir)

    def clean_up(self):
        """Clean up resources before shutting down"""
        self.clean_cache()
        # Clear model cache
        self.model_manager.cache.clear()


def load_config_with_env(path) -> dict:
    """
    Load the configuration file with environment variables.

    Parameters:
    - path (str): The path to the configuration file.

    Returns:
    - dict: The configuration dictionary.

    Raises:
    - FileNotFoundError if the configuration file is not found.
    - yaml.YAMLError if the configuration file is not a valid YAML file.
    """
    with open(path, "r", encoding="utf-8") as file:
        content = file.read()

    # Match ${VAR_NAME}
    pattern = re.compile(r"\$\{(\w+)\}")

    # replace ${VAR_NAME} with os.getenv('VAR_NAME')
    def replacer(match):
        env_var = match.group(1)
        return os.getenv(
            env_var, match.group(0)
        )  # return the original string if the env var is not found

    content = pattern.sub(replacer, content)

    # Load the yaml file
    return yaml.safe_load(content)


class ModelCache:
    """Manager for caching ASR and TTS models"""

    def __init__(self):
        self._cache: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        """get the cached model"""
        return self._cache.get(key)

    def set(self, key: str, model: Any) -> None:
        """set the cached model"""
        self._cache[key] = model

    def remove(self, key: str) -> None:
        """remove the cached model"""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """clear the cache"""
        self._cache.clear()


class ModelManager:
    """Manager for ASR and TTS models"""

    def __init__(self, config: Dict):
        self.config = config
        self._old_config = config.copy()  # save a copy of the initial config
        self.cache = ModelCache()

    def initialize_models(self) -> None:
        """Initialize ASR and TTS models"""
        if self.config.get("VOICE_INPUT_ON", False):
            self._init_asr()
        if self.config.get("TTS_ON", False):
            self._init_tts()

    def _init_asr(self) -> None:
        """Initialize ASR model"""
        from asr.asr_factory import ASRFactory

        asr_model = self.config.get("ASR_MODEL")
        asr_config = self.config.get(asr_model, {})
        self.cache.set("asr", ASRFactory.get_asr_system(asr_model, **asr_config))
        logger.info(f"ASR model {asr_model} loaded successfully")

    def _init_tts(self) -> None:
        """Initialize TTS model"""
        from tts.tts_factory import TTSFactory

        tts_model = self.config.get("TTS_MODEL")
        tts_config = self.config.get(tts_model, {})
        self.cache.set("tts", TTSFactory.get_tts_engine(tts_model, **tts_config))
        logger.info(f"TTS model {tts_model} loaded successfully")

    def update_models(self, new_config: Dict) -> None:
        """Update ASR and TTS models based on new configuration"""
        try:
            # make sure old config is saved
            if not hasattr(self, "_old_config"):
                self._old_config = self.config.copy()

            # check if ASR or TTS models need to be reinitialized
            if self._should_reinit_asr(new_config):
                self.config = new_config  # update current config
                self._update_asr()
            if self._should_reinit_tts(new_config):
                self.config = new_config  # update current config
                self._update_tts()

            self._old_config = new_config.copy()
            self.config = new_config

        except Exception as e:
            logger.error(f"Error during model update: {e}")
            raise

    def _should_reinit_asr(self, new_config: Dict) -> bool:
        """check if ASR model needs to be reinitialized"""
        if self._old_config.get("VOICE_INPUT_ON") != new_config.get("VOICE_INPUT_ON"):
            return True

        old_model = self._old_config.get("ASR_MODEL")
        new_model = new_config.get("ASR_MODEL")
        if old_model != new_model:
            return True

        # if model is the same, check if any settings have changed
        if old_model:
            old_model_config = self._old_config.get(old_model, {})
            new_model_config = new_config.get(old_model, {})

            if old_model_config != new_model_config:
                logger.info(f"ASR model {old_model} settings changed")
                for key in set(old_model_config.keys()) | set(new_model_config.keys()):
                    if old_model_config.get(key) != new_model_config.get(key):
                        logger.debug(
                            f"ASR setting changed - {key}: {old_model_config.get(key)} -> {new_model_config.get(key)}"
                        )
                return True

        return False

    def _should_reinit_tts(self, new_config: Dict) -> bool:
        """check if TTS model needs to be reinitialized"""
        if self._old_config.get("TTS_ON") != new_config.get("TTS_ON"):
            return True

        old_model = self._old_config.get("TTS_MODEL")
        new_model = new_config.get("TTS_MODEL")
        if old_model != new_model:
            return True

        if old_model:
            old_model_config = self._old_config.get(old_model, {})
            new_model_config = new_config.get(old_model, {})

            if old_model_config != new_model_config:
                logger.info(f"TTS model {old_model} settings changed")
                for key in set(old_model_config.keys()) | set(new_model_config.keys()):
                    if old_model_config.get(key) != new_model_config.get(key):
                        logger.debug(
                            f"TTS setting changed - {key}: {old_model_config.get(key)} -> {new_model_config.get(key)}"
                        )
                return True

        return False

    def _update_asr(self) -> None:
        """update ASR model"""
        if self.config.get("VOICE_INPUT_ON", False):
            logger.info("Reinitializing ASR...")
            self._init_asr()
        else:
            logger.info("ASR disabled in new configuration")
            self.cache.remove("asr")

    def _update_tts(self) -> None:
        """update TTS model"""
        if self.config.get("TTS_ON", False):
            logger.info("Reinitializing TTS...")
            self._init_tts()
        else:
            logger.info("TTS disabled in new configuration")
            self.cache.remove("tts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="")
    parser.add_argument("--web", action="store_true", help="Web mode")
    args = parser.parse_args()

    atexit.register(WebSocketServer.clean_cache)
    
    # Load configurations from yaml file
    config = load_config_with_env("conf.yaml")

    config["LIVE2D"] = True  # make sure the live2d is enabled
    
    # Initialize and run the WebSocket server
    server = WebSocketServer(open_llm_vtuber_main_config=config, web=args.web)
    server.run(host=config["HOST"], port=config["PORT"])

