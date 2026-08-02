import io
import inspect
import os
import pkgutil
import re
import subprocess
import builtins
import warnings
import torch
import numpy as np
import soundfile as sf
from .asr_interface import ASRInterface

# FunASR discovers optional submodules recursively during import. If two
# WebSocket clients initialize ASR at the same time, its first lazy import of
# numba can observe a partially initialized module. Load it fully first.
import numba  # noqa: F401


# FunASR probes ``ffmpeg -version`` while importing. The bundled ffmpeg in this
# desktop build can block indefinitely on that probe. ASR receives NumPy audio
# directly, so file decoding through ffmpeg is not needed here.
_check_output = subprocess.check_output


def _check_output_without_ffmpeg_probe(command, *args, **kwargs):
    if command == ["ffmpeg", "-version"]:
        raise FileNotFoundError("Skip ffmpeg probe for NumPy ASR input")
    return _check_output(command, *args, **kwargs)


# FunASR 1.3.x recursively scans its entire package and asks ``inspect`` for
# every registered class's source line during import. Under some Windows TxF
# contexts those directory/source probes fail with WinError 6714. Import only
# the components used by this project and temporarily disable source metadata
# lookup; exact module imports and model loading remain unchanged.
_walk_packages = pkgutil.walk_packages
_get_source_lines = inspect.getsourcelines
_print = builtins.print


def _print_without_unused_ffmpeg_notice(*args, **kwargs):
    message = str(args[0]) if args else ""
    if message.startswith("Notice: ffmpeg is not installed."):
        return
    _print(*args, **kwargs)


subprocess.check_output = _check_output_without_ffmpeg_probe
pkgutil.walk_packages = lambda *args, **kwargs: iter(())
inspect.getsourcelines = lambda obj: ([], 0)
builtins.print = _print_without_unused_ffmpeg_notice
warnings.filterwarnings(
    "ignore",
    message=r"Couldn't find ffmpeg or avconv.*",
    category=RuntimeWarning,
    module=r"pydub\.utils",
)
try:
    from funasr import AutoModel
    from funasr.download.download_model_from_hub import download_model
    import funasr.frontends.wav_frontend  # noqa: F401
    import funasr.models.ct_transformer.model  # noqa: F401
    import funasr.models.fsmn_vad_streaming.encoder  # noqa: F401
    import funasr.models.fsmn_vad_streaming.model  # noqa: F401
    import funasr.models.sanm.encoder  # noqa: F401
    import funasr.models.sense_voice.model  # noqa: F401
    import funasr.models.specaug.specaug  # noqa: F401
    import funasr.tokenizer.char_tokenizer  # noqa: F401
    import funasr.tokenizer.sentencepiece_tokenizer  # noqa: F401
finally:
    subprocess.check_output = _check_output
    pkgutil.walk_packages = _walk_packages
    inspect.getsourcelines = _get_source_lines
    builtins.print = _print


# paraformer-zh is a multi-functional asr model
# use vad, punc, spk or not as you need


class VoiceRecognition(ASRInterface):

    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        language: str = "auto",
        vad_model: str = "fsmn-vad",
        punc_model=None,
        ncpu: int = None,
        hub: str = None,
        device: str = "cpu",
        disable_update: bool = True,
        sample_rate: int = 16000,
        use_itn: bool = False,
    ) -> None:

        resolved_model_name = model_name
        if not os.path.isabs(model_name):
            asr_dir = os.path.dirname(os.path.abspath(__file__))
            project_relative = os.path.normpath(
                os.path.join(os.path.dirname(asr_dir), model_name)
            )
            if os.path.isdir(project_relative):
                resolved_model_name = project_relative

        model_options = {"model": resolved_model_name}
        if os.path.isdir(resolved_model_name):
            model_options = download_model(
                model=os.path.abspath(resolved_model_name),
                hub=hub or "ms",
                device=device,
                ncpu=ncpu,
                disable_update=disable_update,
            )

        model_options.update(
            vad_model=vad_model,
            ncpu=ncpu,
            hub=hub,
            device=device,
            disable_update=disable_update,
            punc_model=punc_model,
            # spk_model="cam++",
        )
        self.model = AutoModel(**model_options)
        self.SAMPLE_RATE = sample_rate
        self.use_itn = use_itn
        self.language = language

        self.asr_with_vad = None

    # Implemented in asr_interface.py
    # def transcribe_with_local_vad(self) -> str:

    def transcribe_np(self, audio: np.ndarray) -> str:

        audio_tensor = torch.tensor(audio, dtype=torch.float32)

        res = self.model.generate(
            input=audio_tensor,
            batch_size_s=300,
            use_itn=self.use_itn,
            language=self.language,
        )

        full_text = res[0]["text"]

        # SenseVoiceSmall may spits out some tags
        # like this: '<|zh|><|NEUTRAL|><|Speech|><|woitn|>欢迎大家来体验达摩院推出的语音识别模型'
        # we should remove those tags from the result

        # remove tags
        full_text = re.sub(r"<\|.*?\|>", "", full_text)
        # the tags can also look like '< | en | > < | EMO _ UNKNOWN | > < | S pe ech | > < | wo itn | > ', so...
        full_text = re.sub(r"< \|.*?\| >", "", full_text)

        return full_text.strip()

    def _numpy_to_wav_in_memory(self, numpy_array: np.ndarray, sample_rate):

        memory_file = io.BytesIO()
        sf.write(memory_file, numpy_array, sample_rate, format="WAV")
        memory_file.seek(0)

        return memory_file
