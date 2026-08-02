import base64
import os

def _audio_metadata(audio_path: str, audio_bytes: bytes) -> tuple[str, float]:
    """Return browser MIME type and a conservative duration estimate."""
    suffix = os.path.splitext(audio_path)[1].lower()
    if suffix == ".wav":
        import io
        import wave

        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            duration = wav_file.getnframes() / max(wav_file.getframerate(), 1)
        return "audio/wav", max(duration, 0.1)

    # Edge TTS produces 48 kbps MP3. Chromium decodes it directly, avoiding
    # an external ffmpeg process that Windows application control may block.
    duration = len(audio_bytes) * 8 / 48_000
    return "audio/mpeg", max(duration, 0.1)


def _speech_envelope(duration: float, chunk_length_ms: int) -> list[float]:
    """Generate a lightweight animation envelope without decoding the audio."""
    chunk_count = max(1, round(duration * 1000 / chunk_length_ms))
    return [0.72 if index % 4 in (1, 2) else 0.32 for index in range(chunk_count)]


class AudioPayloadPreparer:
    def __init__(self, chunk_length_ms: int = 20):
        self.chunk_length_ms: int = chunk_length_ms

    def prepare_audio_payload(
        self, audio_path, instrument_path=None, display_text=None, expression_list=None
    ):
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        with open(audio_path, "rb") as audio_file:
            audio_bytes = audio_file.read()
        audio_mime, duration = _audio_metadata(audio_path, audio_bytes)
        audio_base64 = base64.b64encode(audio_bytes).decode("ascii")

        # Instrument
        instrument_base64 = None
        instrument_mime = None
        if instrument_path and os.path.exists(instrument_path):
            with open(instrument_path, "rb") as instrument_file:
                instrument_bytes = instrument_file.read()
            instrument_mime, _ = _audio_metadata(instrument_path, instrument_bytes)
            instrument_base64 = base64.b64encode(instrument_bytes).decode("ascii")

        volumes = _speech_envelope(duration, self.chunk_length_ms)

        payload = {
            "type": "audio",
            "audio": audio_base64,
            "audio_mime": audio_mime,
            "instrument": instrument_base64,
            "instrument_mime": instrument_mime,
            "volumes": volumes,
            "slice_length": self.chunk_length_ms,
            "text": display_text,
            "expressions": expression_list,
        }

        return payload, duration
