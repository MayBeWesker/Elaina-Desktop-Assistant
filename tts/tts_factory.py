from typing import Type

from .tts_interface import TTSInterface


class TTSFactory:
    """Create the Edge TTS engine used by this distribution."""

    @staticmethod
    def get_tts_engine(engine_type: str, **kwargs) -> Type[TTSInterface]:
        if engine_type != "edgeTTS":
            raise ValueError("This distribution supports edgeTTS only.")

        from .edgeTTS import TTSEngine

        return TTSEngine(kwargs.get("voice"))
