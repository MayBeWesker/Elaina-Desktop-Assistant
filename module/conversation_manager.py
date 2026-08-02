import threading
import queue
import random
import numpy as np
import os
import json
import uuid
from typing import Iterator
import asyncio
import platform
import time
from .computer_utils import (
    capture_active_window_base64,
    get_clipboard_content,
    copy_selected_content,
    input_text as utils_input_text,
)
from .character_manager import match_character_mode
if platform.system() == 'Darwin':
    from .computer_utils import control_computer as utils_control_computer
import re

class ConversationManager:
    def __init__(self, config, llm, asr, tts, live2d, translator, audio_manager, interrupt_manager, claude_api_key = None, verbose=False, loop=None):
        self.config = config
        self.llm = llm
        self.asr = asr
        self.tts = tts
        self.live2d = live2d
        self.translator = translator
        self.audio_manager = audio_manager
        self.interrupt_manager = interrupt_manager
        self.claude_api_key = claude_api_key
        self.loop = loop
        assert self.loop is not None, "loop is None"
        self.verbose = verbose
        self.heard_sentence = ""
        self.character_output_func = None
        self._current_model = "conf"  # "conf" = cloud (DeepSeek), "local_model" = local Ollama
        # self.functions = self.get_tool_functions()

    def set_character_output_func(self, output_func):
        self.character_output_func = output_func

    def _switch_model(self, target):
        """Switch LLM model between cloud (DeepSeek) and local (Ollama)."""
        import yaml
        import os

        config_path = f"config_alts/{target}.yaml" if target != "conf" else "conf.yaml"
        if not os.path.exists(config_path):
            print(f"[Switch] Config file not found: {config_path}")
            return

        with open(config_path, "r", encoding="utf-8") as f:
            new_config = yaml.safe_load(f)

        # Update LLM-relevant config
        llm_provider = new_config.get("LLM_PROVIDER", "ollama")
        llm_config = new_config.get(llm_provider, {})

        self.config["LLM_PROVIDER"] = llm_provider
        self.config[llm_provider] = llm_config
        if new_config.get("PERSONA_CHOICE"):
            self.config["PERSONA_CHOICE"] = new_config["PERSONA_CHOICE"]

        # Re-initialize LLM
        from llm.llm_factory import LLMFactory
        from prompts import prompt_loader

        system_prompt, tools = self._get_system_prompt_and_tools_internal()

        self.llm = LLMFactory.create_llm(
            llm_provider=llm_provider,
            SYSTEM_PROMPT=system_prompt,
            tools=tools,
            caller=None,
            **llm_config
        )
        self.interrupt_manager.llm = self.llm
        self._current_model = target
        print(f"[Switch] Model switched to: {target} ({llm_config.get('MODEL', 'unknown')})")

    def _get_system_prompt_and_tools_internal(self):
        """Internal helper to get system prompt and tools for re-init."""
        from prompts import prompt_loader

        if self.config.get("PERSONA_CHOICE"):
            system_prompt = prompt_loader.load_persona(self.config.get("PERSONA_CHOICE"))
        else:
            system_prompt = self.config.get("DEFAULT_PERSONA_PROMPT_IN_YAML")

        song_list = []
        song_path = "./sing/original"
        if os.path.exists(song_path):
            song_list = [os.path.splitext(s)[0] for s in os.listdir(song_path)]

        system_prompt += prompt_loader.load_util("tools_prompt").replace(
            "[<insert_song_list>]", str(song_list)
        )

        if self.live2d is not None:
            system_prompt += prompt_loader.load_util(
                self.config.get("LIVE2D_Expression_Prompt")
            ).replace("[<insert_emomap_keys>]", self.live2d.emo_str)

        tools = prompt_loader.load_util_json("tools")
        tools[0]["function"]["parameters"]["properties"]["song_name"]["enum"] = song_list

        return system_prompt, tools
        
    def get_prompt_and_image(self, user_input: str | np.ndarray | None = None, clipboard_data: dict | None = None) -> tuple[str, str | None]:
        image_base64 = None

        # Privacy-first context policy: normal conversation never receives the
        # clipboard or a screenshot. Visual context is captured only after ASR
        # has recognized an explicit request to inspect the current window.
        visual_phrases = (
            "当前窗口", "现在的窗口", "这个窗口", "窗口中", "窗口里",
            "当前页面", "这个页面", "当前界面", "这个界面",
            "屏幕上", "屏幕中", "屏幕内容", "屏幕显示",
            "看看屏幕", "看下屏幕", "看一下屏幕", "看我的屏幕",
            "你看到什么", "你看到了什么",
            "看看我在做什么", "看看我正在做什么", "我正在处理什么",
            "根据当前窗口", "根据这个窗口", "根据当前页面", "根据这个页面",
            "根据当前界面", "根据这个界面", "结合当前界面",
            "实时看到", "实时查看",
            "这个报错", "这里的报错", "界面上的",
        )
        clipboard_phrases = ("剪贴板", "我复制的", "复制内容", "刚刚复制", "刚复制")
        explicit_visual_pattern = re.compile(
            r"(看|查看|检查|分析|识别|读).{0,10}(屏幕|窗口|页面|界面)"
            r"|(?:屏幕|窗口|页面|界面).{0,10}(内容|显示|东西|报错|是什么)"
            r"|(?:根据|结合).{0,8}(屏幕|窗口|页面|界面).{0,12}(建议|怎么办|怎么做|处理|操作)"
        )
        requests_visual_context = (
            any(phrase in user_input for phrase in visual_phrases)
            or bool(explicit_visual_pattern.search(user_input))
        )
        requests_clipboard_context = any(phrase in user_input for phrase in clipboard_phrases)

        if requests_visual_context:
            print(f"[Vision] Explicit screen request detected: {user_input}")
            try:
                image_base64 = capture_active_window_base64()
                if image_base64:
                    vision_model = (
                        self.config.get(self.config.get("LLM_PROVIDER", ""), {})
                        .get("V_MODEL", "not configured")
                    )
                    print(f"[Vision] Sending screenshot to vision model: {vision_model}")
                    user_input += (
                        "\n以下图片是用户明确要求查看的当前活动窗口截图。"
                        "只回答用户本次询问的内容，不要无故罗列无关报错。"
                    )
            except Exception as error:
                print(f"[Vision] Failed to capture active window: {error}")

        if requests_clipboard_context:
            clipboard_data = get_clipboard_content()
            clipboard_text = (clipboard_data or {}).get("text", "").strip()
            if clipboard_text:
                user_input += f"\n用户明确要求查看的剪贴板文本：###\n{clipboard_text}\n###\n"
            if not image_base64:
                image_base64 = (clipboard_data or {}).get("image")

        return user_input, image_base64
        

    def conversation_chain(self, user_input=None, clipboard_data=None):
        if not self.interrupt_manager.wait_continue_flag(): 
            print(
                ">> Execution flag not set. In interruption state for too long. Exiting     conversation chain."
            )
            raise InterruptedError(
                "Conversation chain interrupted. Wait flag timeout reached."
            )

        color_code = random.randint(0, 3)
        c = [None] * 4
        c[0] = "\033[91m"
        c[1] = "\033[94m"
        c[2] = "\033[92m"
        c[3] = "\033[0m"

        print(f"{c[color_code]}New Conversation Chain started!")

        if user_input is None:
            user_input = self.get_user_input()
        elif isinstance(user_input, np.ndarray):
            print(f"\n[ASR] Transcribing audio: {len(user_input)} samples, {len(user_input)/16000:.1f}s, max_amplitude={user_input.max():.4f}")
            try:
                user_input = self.asr.transcribe_np(user_input)
                print(f"[ASR] Result: '{user_input}' (len={len(user_input)})")
            except Exception as e:
                print(f"[ASR] ERROR: {e}")
                import traceback
                traceback.print_exc()
                return ""

        # Character appearance voice commands are handled locally, without an
        # LLM round trip, so the visual change is immediate and deterministic.
        character_mode = match_character_mode(user_input)
        if character_mode:
            print(f"[Character] Switching to: {character_mode['name']}")
            if self.character_output_func:
                self.character_output_func(character_mode)
            confirmation = f"已切换到{character_mode['name']}模式"
            if self.config.get("TTS_ON", False):
                self.audio_manager.play_text(confirmation)
            return confirmation

        # Model switching voice commands
        if "切换本地模型" in user_input or "本地模型切换" in user_input:
            print("[Switch] Switching to local Ollama model...")
            self._switch_model("local_model")
            self.audio_manager.play_text("已切换到本地模型")
            return "已切换到本地模型"
        elif "切换云端模型" in user_input or "云端模型切换" in user_input:
            print("[Switch] Switching to DeepSeek cloud model...")
            self._switch_model("conf")
            self.audio_manager.play_text("已切换到云端模型")
            return "已切换到云端模型"

        if user_input.strip().lower() == self.config.get("EXIT_PHRASE", "exit").lower():
            print("Exiting...")
            exit()

        print(f"User input: {user_input}")

        prompt, image_base64 = self.get_prompt_and_image(user_input, clipboard_data)
        
        chat_completion: Iterator[str] = self.llm.chat_iter(prompt, image_base64)

        if not self.config.get("TTS_ON", False):
            full_response = ""
            for char in chat_completion:
                if self.interrupt_manager.in_interrupt():
                    self.interrupt_manager.interrupt_post_processing()
                    print("\nInterrupted!")
                    return None
                full_response += char
                print(char, end="")
            return full_response

        full_response = self.speak(chat_completion, user_input)
        if self.verbose:
            print(f"\nComplete response: [\n{full_response}\n]")

        print(f"{c[color_code]}Conversation completed.")
        return full_response


    def get_user_input(self) -> str:
        if self.config.get("VOICE_INPUT_ON", False):
            print("Listening from the microphone...")
            return self.asr.transcribe_with_local_vad()
        else:
            return input("\n>> ")

    def speak(self, chat_completion: Iterator[str], user_input: str) -> str:
        full_response = ""
        if self.config.get("SAY_SENTENCE_SEPARATELY", True):
            full_response = self.speak_by_sentence_chain(
                chat_completion, user_input
            )
        else:
            full_response = ""
            for char in chat_completion:
                if self.interrupt_manager.in_interrupt():
                    print("\nInterrupted!")
                    self.interrupt_manager.interrupt_post_processing()
                    return None
                print(char, end="")
                full_response += char
            print("\n")
            
            if self.live2d:
                tts_target_sentence = self.live2d.remove_emotion_keywords(full_response[0])
            else:
                tts_target_sentence = full_response[0]
                
            if self.translator and self.config.get("TRANSLATE_AUDIO", False):
                print("Translating...")
                tts_target_sentence = self.translator.translate(tts_target_sentence)
                print(f"Translated: {tts_target_sentence}")

            filename = self.audio_manager.generate_audio_file(tts_target_sentence, "temp")

            if not self.interrupt_manager.in_interrupt():
                self.audio_manager.play_audio_file(
                    sentence=full_response,
                    filepath=filename,
                    instrument_filepath=None
                )
            if self.interrupt_manager.in_interrupt():
                self.interrupt_manager.interrupt_post_processing()

        return full_response

    def speak_by_sentence_chain(self, chat_completion: Iterator[str], user_input: str) -> str:
        full_response = [""]

        sentence_queue = queue.Queue()
        audio_queue = queue.Queue()
        index = 0

        def producer_worker():
            nonlocal index
            try:
                sentence_buffer = ""
                for char in chat_completion:
                    if self.interrupt_manager.in_interrupt():
                        print("Producer interrupted")
                        return None
                    
                    if char:
                        print(char, end="", flush=True)
                        sentence_buffer += char
                        full_response[0] += char
                        check_result = self.check(sentence_buffer)
                        if check_result == "sing-song":
                            match = re.search(r'\{.*?\}', sentence_buffer)
                            if match:
                                self.sing_song(match.group(0))
                                sentence_buffer = re.sub(r'\{.*?\}', '', sentence_buffer)
                            else:
                                print("Invalid JSON format in sing mode")
                        # elif check_result == "computer-control":
                        #     match = re.search(r'\{.*?\}', sentence_buffer)
                        #     if match:
                        #         future = asyncio.run_coroutine_threadsafe(
                        #             self.control_computer(match.group(0)),
                        #             self.loop
                        #         )
                        #         try:
                        #             _ = future.result() 
                        #         except Exception as e:
                        #             print(f"Error running control_computer coroutine: {e}")
                        #         sentence_buffer = re.sub(r'\{.*?\}', '', sentence_buffer)
                        #     else:
                        #         print("Invalid JSON format in computer control mode")
                        # elif check_result == "input-text":
                        #     match = re.search(r'\[text_input_start\](.*?)\[text_input_end\]', sentence_buffer, re.DOTALL)
                        #     if match:
                        #         text_to_input = match.group(1)
                        #         self.input_text(text_to_input)
                        #         sentence_buffer = ""
                        #     else:
                        #         match = re.search(r'\[text_input_start\](.*)', sentence_buffer, re.DOTALL)
                        #         if match:
                        #             text_to_input = match.group(1)
                        #             self.input_text(text_to_input)
                        #             sentence_buffer = "[text_input_start]"
                        elif check_result:
                            if self.verbose:
                                print("\n")
                            if self.interrupt_manager.in_interrupt():
                                print("Producer interrupted")
                                return None
                            sentence_queue.put((index, sentence_buffer))
                            index += 1
                            sentence_buffer = ""

                if sentence_buffer:
                    if self.interrupt_manager.in_interrupt():
                        print("Producer interrupted")
                        return None
                    print("\n")
                    sentence_queue.put((index, sentence_buffer))
                    index += 1

            except Exception as e:
                print(
                    f"Producer error: Error processing sentence.\n{e}",
                    "Producer stopped\n",
                )
                return
            finally:
                sentence_queue.put((None, None))

        def tts_worker():
            try:
                while True:
                    if self.interrupt_manager.in_interrupt():
                        print("TTS worker interrupted")
                        return None
                    idx, sentence = sentence_queue.get()
                    if idx is None:
                        sentence_queue.put((None, None))
                        break

                    if self.live2d:
                        tts_target_sentence = self.live2d.remove_emotion_keywords(sentence)
                    else:
                        tts_target_sentence = sentence

                    if self.translator and self.config.get("TRANSLATE_AUDIO", False):
                        try:
                            print("Translating...")
                            tts_target_sentence = self.translator.translate(tts_target_sentence)
                            print(f"Translated: {tts_target_sentence}")
                        except Exception as e:
                            print(f"Error translating: {e}")
                            print(f"Text: {tts_target_sentence}")
                            print("Skipping...")

                    audio_filepath = self.audio_manager.generate_audio_file(
                        tts_target_sentence, file_name_no_ext=f"temp-{idx}"
                    )

                    if self.interrupt_manager.in_interrupt():
                        print("TTS worker interrupted")
                        return None

                    audio_info = {
                        "index": idx,
                        "sentence": sentence,
                        "audio_filepath": audio_filepath,
                    }
                    audio_queue.put(audio_info)
            except Exception as e:
                print(
                    f"TTS worker error: Error generating audio for sentence.\n{e}",
                    "TTS worker stopped\n",
                )
                return
            finally:
                audio_queue.put(None)  

        def consumer_worker():
            expected_index = 0
            audio_buffer = {}
            self.heard_sentence = ""
            try:
                while True:
                    if self.interrupt_manager.in_interrupt():
                        print("Consumer interrupted")
                        return None
                    audio_info = audio_queue.get()
                    if self.interrupt_manager.in_interrupt():
                        print("Consumer interrupted after receiving queued audio")
                        return None
                    if audio_info is None:
                        break

                    if audio_info:
                        self.heard_sentence += audio_info["sentence"]
                    idx = audio_info["index"]
                    audio_buffer[idx] = audio_info

                    while expected_index in audio_buffer:
                        if self.interrupt_manager.in_interrupt():
                            print("Consumer interrupted before audio playback")
                            return None
                        info = audio_buffer.pop(expected_index)
                        if self.verbose:
                            print("\n")
                        self.audio_manager.play_audio_file(
                            sentence=info["sentence"],
                            filepath=info["audio_filepath"],
                            instrument_filepath=None
                        )
                        expected_index += 1

            except Exception as e:
                print(
                    f"Consumer error: Error playing audio.\n{e}",
                    "Consumer stopped\n",
                )
                return

        producer_thread = threading.Thread(target=producer_worker)
        tts_thread = threading.Thread(target=tts_worker)
        consumer_thread = threading.Thread(target=consumer_worker)

        producer_thread.start()
        tts_thread.start()
        consumer_thread.start()

        producer_thread.join()
        tts_thread.join()
        consumer_thread.join()

        if self.interrupt_manager.in_interrupt():
            self.interrupt_manager.interrupt_post_processing()

        return full_response[0]
    

    def check(self, text: str):
        """
        Check if the text contains a tool call / is the end of a sentence.
        """
        if ("sing_song" in text and "}" in text): 
            return "sing-song"
        
        # if ("computer_control" in text and "}" in text):
        #     return "computer-control"
        # if ("[text_input_start]" in text):
        #     return False if text.count('[') >= 2 and text.count(']') < 2 else "input-text"

        white_list = ["...", "Dr.", "Mr.", "Ms.", "Mrs.", "Jr.", "Sr.", "St.", "Ave.", "Rd.", 
                     "Blvd.", "Dept.", "Univ.", "Prof.", "Ph.D.", "M.D.", "U.S.", "U.K.", 
                     "U.N.", "E.U.", "U.S.A.", "U.K.", "U.S.S.R.", "U.A.E."]
        
        if any(text.strip().endswith(item) for item in white_list): 
            return False

        punctuation_blacklist = [".", "?", "!", "。", "；", "？", "！", "…", "〰", "〜", "～", "！"]
        return any(text.strip().endswith(punct) for punct in punctuation_blacklist)  # and not "sing_song" in text and not "computer_control" in text and not "input_text" in text

    def sing_song(self, sentence):
        print("sing mode activated")
        try:
            data = json.loads(sentence)
            song_name = data.get("song_name")
        except json.JSONDecodeError:
            print("Invalid JSON format in response")
            return

        if not song_name:
            self.audio_manager.play_text("This song, even I have yet to master.")
            return

        converted_vocal_path = os.path.join('./sing/converted_vocal', f'{song_name}.wav')
        instrument_path = os.path.join('./sing/instrument', f'{song_name}.wav')

        if not os.path.exists(converted_vocal_path) or not os.path.exists(instrument_path):
            self.audio_manager.play_text("This song, even I have yet to master.")
            return

        self.audio_manager.play_text(f"Please enjoy {song_name}")

        self.audio_manager.play_audio_file(
            sentence = song_name,
            filepath=converted_vocal_path,
            instrument_filepath = instrument_path
        )     
        
    # async def control_computer(self, sentence):
    #     print("computer control mode activated")
        
    #     if platform.system() != 'Darwin':
    #         self.audio_manager.play_text("This system is currently not supported.")
    #         return
        
    #     try:
    #         data = json.loads(sentence)
    #         instruction = data.get("computer_control")
    #     except json.JSONDecodeError:
    #         print("Invalid JSON format in response")
    #         return
        
    #     print("computer control mode activated")
        
    #     async def api_response_callback(response):
    #         data = json.loads(response.text)["content"]
    #         # print(json.dumps(data, indent=4))
            
    #         for item in data:
    #             if item["type"] == "text":
    #                 text = item["text"]
    #                 print(text)
    #                 self.audio_manager.play_text(text)
        
    #     await utils_control_computer(self.claude_api_key, instruction, api_response_callback)
        
    # def input_text(self, text):
    #     # print("input text mode activated")
    #     utils_input_text(text)
        
    # def get_tool_functions(self):
    #     return {
    #         "sing_song" : self.sing_song,
    #         "control_computer" : self.control_computer
    #     }
        
    # def call_tool_function(self, function_name, *args):
    #     if function_name in self.functions:
    #         self.functions[function_name](*args)
    #     else:
    #         print(f"Function {function_name} not found")
    
