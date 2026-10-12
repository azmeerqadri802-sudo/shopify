"""One-shot microphone capture and speech transcription."""

from __future__ import annotations


class VoiceError(RuntimeError):
    """User-friendly voice capture error."""


def transcribe_once(language: str = "en-US") -> str:
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise VoiceError("Speech recognition is unavailable. Reinstall requirements.txt.") from exc
    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = recognizer.listen(source, timeout=6, phrase_time_limit=18)
    except OSError as exc:
        raise VoiceError("Microphone unavailable. Connect one and check OS permissions.") from exc
    except sr.WaitTimeoutError as exc:
        raise VoiceError("No speech detected. Press the microphone and try again.") from exc
    try:
        # Audio is sent to Google's speech-recognition endpoint for transcription.
        text = recognizer.recognize_google(audio, language=language or "en-US")
    except sr.UnknownValueError as exc:
        raise VoiceError("I could not understand that recording. Please try again.") from exc
    except sr.RequestError as exc:
        raise VoiceError("Speech transcription failed. Check the internet connection.") from exc
    if not text.strip():
        raise VoiceError("The transcription was empty.")
    return text.strip()

