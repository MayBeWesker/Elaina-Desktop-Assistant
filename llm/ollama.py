""" Description: This file contains the implementation of the `ollama` class.
This class is responsible for handling the interaction with the OpenAI API for 
language generation.
And it is compatible with all of the OpenAI Compatible endpoints, including Ollama, 
OpenAI, and more.
"""

from typing import Iterator
import json
from openai import OpenAI
from zhipuai import ZhipuAI
from .llm_interface import LLMInterface


class LLM(LLMInterface):

    def __init__(
        self,
        base_url: str,
        model: str,
        tools: list[dict],
        caller: callable,
        system: str,
        callback=print,
        organization_id: str = "z",
        project_id: str = "z",
        llm_api_key: str = "z",

        v_base_url: str = None,
        v_model: str = None,
        v_organization_id: str = "z",
        v_project_id: str = "z",
        vllm_api_key: str = "z",
        verbose: bool = False,
        clipboard_history: bool = None,
        max_history_cnt: int = -1,
        max_tokens: int = 2048,
        reasoning_effort: str | None = None,
        v_reasoning_effort: str | None = None,
    ):
        """
        Initializes an instance of the `ollama` class.

        Parameters:
        - base_url (str): The base URL for the OpenAI API.
        - model (str): The model to be used for language generation.
        - system (str): The system to be used for language generation.
        - callback [DEPRECATED] (function, optional): The callback function to be called after each API call. Defaults to `print`.
        - organization_id (str, optional): The organization ID for the OpenAI API. Defaults to an empty string.
        - project_id (str, optional): The project ID for the OpenAI API. Defaults to an empty string.
        - llm_api_key (str, optional): The API key for the OpenAI API. Defaults to an empty string.
        - verbose (bool, optional): Whether to enable verbose mode. Defaults to `False`.
        """

        self.base_url = base_url
        # Keep legacy DeepSeek configurations usable after the API renamed
        # ``deepseek-chat`` to the v4 model family.
        if "api.deepseek.com" in (base_url or "") and model == "deepseek-chat":
            model = "deepseek-v4-flash"
        self.model = model
        self.v_base_url = v_base_url
        self.v_model = v_model
        self.system = system
        self.callback = callback
        self.memory = []
        self.verbose = verbose
        try:
            if "glm" in model:
                self.client = ZhipuAI(
                    api_key = llm_api_key
                )
            else: 
                self.client = OpenAI(
                    base_url=base_url,
                    organization=organization_id,
                    project=project_id,
                    api_key=llm_api_key,
                )

            if v_model:
                if "glm" in v_model:
                    self.v_client = ZhipuAI(
                        api_key = vllm_api_key
                    )
                else:
                    self.v_client = OpenAI(
                        base_url=v_base_url,
                        organization=v_organization_id,
                        project=v_project_id,
                        api_key=vllm_api_key,
                    )
            elif verbose:
                print("Vision model not provided.")
        except Exception as e:
            print("Error initializing the client: " + str(e))
            return
        
        self.clipboard_history = clipboard_history
        self.max_history_cnt = max_history_cnt
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.v_reasoning_effort = v_reasoning_effort

        self.__set_system(system)

        if self.verbose:
            self.__printDebugInfo()

    def __set_system(self, system):
        """
        Set the system prompt
        system: str
            the system prompt
        """
        self.system = system
        self.memory.append(
            {
                "role": "system",
                "content": system,
            }
        )

    def __print_memory(self):
        """
        Print the memory
        """
        print("Memory:\n========\n")
        # for message in self.memory:
        print(self.memory)
        print("\n========\n")

    def __printDebugInfo(self):
        print(" -- Base URL: " + self.base_url)
        print(" -- Model: " + self.model)
        print(" -- System: " + self.system)

    def _normalize_memory(self) -> None:
        """Keep exactly one system message at the beginning."""
        conversation = [
            message
            for message in self.memory
            if message.get("role") != "system"
        ]
        self.memory = [
            {"role": "system", "content": self.system},
            *conversation,
        ]

    def chat_iter(self, prompt: str, image_base64 = None) -> Iterator[str]:
        prompt += "\n请使用中文回复。"

        self._normalize_memory()

        # Trim old conversation history for performance (keep only recent N exchanges)
        if self.max_history_cnt > 0:
            max_msgs = self.max_history_cnt * 2 + 1  # N exchanges + system prompt
            if len(self.memory) > max_msgs:
                # Keep system message + last N exchanges
                self.memory = [self.memory[0]] + self.memory[-(max_msgs - 1):]

        vision_flag = False
        request_messages = self.memory

        if image_base64 == None:
            self.memory.append(
                {
                    "role": "user",
                    "content": prompt,
                }
            )
        else:
            vision_flag = True
            # Vision uses a fresh request instead of reusing cloud-model history.
            # Some local multimodal chat templates reject mixed histories even
            # when their system message originally appeared first.
            request_messages = [
                {
                    "role": "system",
                    "content": self.system,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_base64 if "glm" in self.v_model else f"data:image/png;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ]
            
            
        if vision_flag:
            client_to_use = self.v_client
            model_to_use = self.v_model
        else:
            client_to_use = self.client
            model_to_use = self.model

        if self.verbose:
            self.__print_memory()
            print(" -- Base URL: " + self.base_url)
            print(" -- Model: " + self.model)
            print(" -- System: " + self.system)
            print(" -- Prompt: " + prompt + "\n\n")

        chat_completion = []
        try:
            request_options = dict(
                messages=request_messages,
                model=model_to_use,
                stream=True,
                max_tokens=self.max_tokens,
            )
            reasoning_effort = self.v_reasoning_effort if vision_flag else self.reasoning_effort
            if reasoning_effort:
                request_options["reasoning_effort"] = reasoning_effort
            chat_completion = client_to_use.chat.completions.create(**request_options)
        except Exception as e:
            print("Error calling the chat endpoint: " + str(e))
            failed_base_url = self.v_base_url if vision_flag else self.base_url
            failed_model = self.v_model if vision_flag else self.model
            print(" -- Base URL: " + str(failed_base_url))
            print(" -- Model: " + str(failed_model))
            print(
                " -- Message roles: "
                + str([message.get("role") for message in request_messages])
            )
            return iter(())

        # a generator to give back an iterator to the response that will store
        # the complete response in memory once the iteration is done
        def _generate_and_store_response():
            complete_response = ""
            for chunk in chat_completion:
                delta = chunk.choices[0].delta
                content = getattr(delta, 'content', None)
                # Skip reasoning/thinking tokens from local models
                if content is None:
                    continue
                yield content
                complete_response += content

            if not vision_flag:
                self.memory.append(
                    {
                        "role": "assistant",
                        "content": complete_response,
                    }
                )

            def serialize_memory(memory, filename):
                with open(filename, "w") as file:
                    json.dump(memory, file)

            serialize_memory(self.memory, "mem.json")
            return

        return _generate_and_store_response()

    def handle_interrupt(self, heard_response: str) -> None:
        if self.memory[-1]["role"] == "assistant":
            self.memory[-1]["content"] = heard_response + "..."
        else:
            if heard_response:
                self.memory.append(
                    {
                        "role": "assistant",
                        "content": heard_response + "...",
                    }
                )
        self.memory.append(
            {
                "role": "system",
                "content": "[Interrupted by user]",
            }
        )


def test():
    llm = LLM(
        base_url="http://localhost:11434/v1",
        model="llama3:latest",
        callback=print,
        system='You are a sarcastic AI chatbot who loves to the jokes "Get out and touch some grass"',
        organization_id="organization_id",
        project_id="project_id",
        llm_api_key="llm_api_key",
        verbose=True,
    )
    while True:
        print("\n>> (Press Ctrl+C to exit.)")
        chat_complet = llm.chat_iter(input(">> "))

        for chunk in chat_complet:
            if chunk:
                print(chunk, end="")


if __name__ == "__main__":
    test()
