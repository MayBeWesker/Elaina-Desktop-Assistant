from typing import Type

from .asr_interface import ASRInterface


class ASRFactory:
    """Create the FunASR engine used by this distribution."""

    @staticmethod
    def get_asr_system(system_name: str, **kwargs) -> Type[ASRInterface]:
        if system_name != "FunASR":
            raise ValueError("This distribution supports FunASR only.")

        from .fun_asr import VoiceRecognition

        return VoiceRecognition(
            model_name=kwargs.get("model_name"),
            vad_model=kwargs.get("vad_model"),
            punc_model=kwargs.get("punc_model"),
            ncpu=kwargs.get("ncpu"),
            hub=kwargs.get("hub"),
            device=kwargs.get("device"),
            language=kwargs.get("language"),
            use_itn=kwargs.get("use_itn"),
        )
