"""
friendmoody Demucs Stem Separation Server
==========================================
Flask + Demucs (htdemucs_ft) stem separation server.
Receives HTTP POST /separate from n8n, separates stems, returns results.

Model: htdemucs_ft (4 stems: drums, bass, other, vocals)
Endpoint: POST /separate  { "url": "...", "stems": ["vocals","other"] }
"""

import gc
import os
import shutil
import subprocess
import tempfile
import uuid

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MAX_DURATION_SEC = 300
DEFAULT_STEMS    = ["vocals", "other"]
MODEL_NAME       = "htdemucs_ft"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download_audio(url: str, dest_path: str) -> None:
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)


def _get_extension(url: str) -> str:
    lower = url.lower().split("?")[0]
    for ext in (".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac"):
        if lower.endswith(ext):
            return ext
    return ".mp3"


def _trim_audio(src: str, dst: str, duration: int) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", src,
        "-t", str(duration),
        "-c", "copy",
        dst,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _run_demucs(input_path: str, out_dir: str, stems: list) -> dict:
    cmd = [
        "python3", "-m", "demucs.separate",
        "-n", MODEL_NAME,
        "--out", out_dir,
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Demucs failed:\n{result.stderr[-2000:]}")

    track_name = os.path.splitext(os.path.basename(input_path))[0]
    stem_dir   = os.path.join(out_dir, MODEL_NAME, track_name)

    output = {}
    for stem in ["drums", "bass", "other", "vocals"]:
        stem_path = os.path.join(stem_dir, f"{stem}.wav")
        if os.path.exists(stem_path):
            output[stem] = stem_path

    return output


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "friendmoody-demucs-server",
        "model":   MODEL_NAME,
        "version": "1.0.0",
    })


@app.route("/separate", methods=["POST"])
def separate():
    body = request.get_json(silent=True)
    if not body or "url" not in body:
        return jsonify({"error": "Request body must include 'url'"}), 400

    audio_url = body["url"]
    requested_stems = body.get("stems", DEFAULT_STEMS)
    valid_stems = [s for s in requested_stems if s in {"drums", "bass", "other", "vocals"}]
    if not valid_stems:
        valid_stems = DEFAULT_STEMS

    tmp_dir = tempfile.mkdtemp(prefix="demucs_")
    try:
        ext = _get_extension(audio_url)
        input_path   = os.path.join(tmp_dir, f"input{ext}")
        _download_audio(audio_url, input_path)

        trimmed_path = os.path.join(tmp_dir, "trimmed.wav")
        _trim_audio(input_path, trimmed_path, MAX_DURATION_SEC)

        out_dir = os.path.join(tmp_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        all_stems = _run_demucs(trimmed_path, out_dir, valid_stems)

        import base64
        stems_out  = {}
        stems_meta = {}
        for stem_name in valid_stems:
            if stem_name not in all_stems:
                continue
            stem_path = all_stems[stem_name]
            file_size = os.path.getsize(stem_path)
            with open(stem_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            stems_out[stem_name]  = f"data:audio/wav;base64,{b64}"
            stems_meta[stem_name] = {"size_bytes": file_size}

        return jsonify({
            "status": "success",
            "model":  MODEL_NAME,
            "stems":  stems_out,
            "meta":   stems_meta,
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Demucs timed out (>600s)"}), 504
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        gc.collect()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
