from typing import Type

from .llm_interface import LLMInterface
from .ollama import LLM as OpenAICompatibleLLM


class LLMFactory:
    """Create the single supported OpenAI-compatible LLM backend."""

    @staticmethod
    def create_llm(llm_provider, **kwargs) -> Type[LLMInterface]:
        if llm_provider != "ollama":
            raise ValueError(
                "This distribution supports the 'ollama' OpenAI-compatible provider only."
            )

        return OpenAICompatibleLLM(
            system=kwargs.get("SYSTEM_PROMPT"),
            tools=kwargs.get("tools"),
            caller=kwargs.get("caller"),
            base_url=kwargs.get("BASE_URL"),
            model=kwargs.get("MODEL"),
            llm_api_key=kwargs.get("LLM_API_KEY"),
            project_id=kwargs.get("PROJECT_ID"),
            organization_id=kwargs.get("ORGANIZATION_ID"),
            verbose=kwargs.get("VERBOSE", False),
            v_base_url=kwargs.get("V_BASE_URL"),
            v_model=kwargs.get("V_MODEL"),
            v_organization_id=kwargs.get("V_ORGANIZATION_ID"),
            v_project_id=kwargs.get("V_PROJECT_ID"),
            vllm_api_key=kwargs.get("VLLM_API_KEY"),
            clipboard_history=kwargs.get("CLIPBOARD_HISTORY", False),
            max_history_cnt=kwargs.get("MAX_HISTORY_CNT", -1),
            max_tokens=kwargs.get("MAX_TOKENS", 2048),
            reasoning_effort=kwargs.get("REASONING_EFFORT"),
            v_reasoning_effort=kwargs.get("V_REASONING_EFFORT"),
        )
