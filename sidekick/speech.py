"""Speech -> text through OpenAI transcription. Audio is sent to OpenAI and not stored.

The browser records (MediaRecorder) and posts the raw bytes to /api/transcribe; the key stays here.
"""
import json
import os
import urllib.request
import uuid

from . import envfile

MAX_BYTES = 5 * 1024 * 1024          # about a minute of speech
EXT = {"webm": "webm", "mp4": "mp4", "ogg": "ogg", "wav": "wav", "mpeg": "mp3", "mp3": "mp3", "m4a": "m4a", "aac": "m4a"}
HINT = ("Toy block build request. Words: cube, plank, roof, arch, pillar, bar, cylinder, tall cylinder, "
        "on top of, next to, with, then, two, three.")


class SpeechError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status, self.msg = status, msg


def extension(mime):
    """'audio/webm;codecs=opus' -> 'webm'; unknown types default to webm."""
    sub = (mime or "").split(";")[0].split("/")[-1].strip().lower()
    return EXT.get(sub, "webm")


def multipart(audio, mime, fields):
    """-> (body, content_type). Hand-built multipart/form-data so there is no extra dependency."""
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.{extension(mime)}"\r\n'
                  f'Content-Type: {(mime or "audio/webm").split(";")[0]}\r\n\r\n').encode())
    parts.append(audio)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(audio, mime):
    """Audio bytes -> text. Raises SpeechError(status, message) with a message that is safe to show."""
    if not audio:
        raise SpeechError(400, "No audio received.")
    if len(audio) > MAX_BYTES:
        raise SpeechError(413, "That recording is too long. Keep it under about a minute.")
    key = envfile.api_key()
    if not key:
        raise SpeechError(503, "Voice needs OPENAI_API_KEY in .env. Typed chat still works.")
    body, ctype = multipart(audio, mime, {"model": os.environ.get("OPENAI_STT_MODEL", "whisper-1"),
                                          "language": "en", "response_format": "json", "prompt": HINT})
    req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", body,
                                 {"Content-Type": ctype, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return str(json.loads(r.read()).get("text", "")).strip()
    except urllib.error.HTTPError as e:      # never forward OpenAI's body: it can echo request details
        print(f"speech: OpenAI returned HTTP {e.code}", flush=True)
        why = {400: "It couldn't read that audio. Try recording again.",
               401: "The OpenAI API key was rejected. Check OPENAI_API_KEY in .env.",
               429: "OpenAI says the key is out of credit or rate limited."}.get(e.code, f"The transcription service returned an error ({e.code}).")
        raise SpeechError(502, why)
    except Exception as e:
        print(f"speech: transcription failed ({type(e).__name__})", flush=True)
        raise SpeechError(502, "Couldn't reach the transcription service. Is the internet up?")
