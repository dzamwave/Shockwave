import os
import sys
import re
from pathlib import Path

# Suppress Hugging Face warnings
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import config

from huggingface_hub import snapshot_download

WHISPER_REPOS = {
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
    "medium": "Systran/faster-whisper-medium",
    "small": "Systran/faster-whisper-small",
    "base": "Systran/faster-whisper-base",
    "tiny": "Systran/faster-whisper-tiny"
}

def is_whisper_downloaded():
    target_dir = config.WHISPER_MODEL_PATH if config.WHISPER_MODEL_PATH else config.WHISPER_DIR
    if os.path.exists(target_dir) and (os.path.exists(os.path.join(target_dir, "model.bin")) or os.path.exists(os.path.join(target_dir, "model.safetensors"))):
        return True
    return False

def is_gigaam_downloaded():
    target_dir = config.GIGAAM_MODEL_PATH if config.GIGAAM_MODEL_PATH else config.GIGAAM_DIR
    return _onnx_model_ready(target_dir, config.GIGAAM_MODEL, config.GIGAAM_QUANTIZATION)

def is_parakeet_downloaded():
    return _onnx_model_ready(config.PARAKEET_DIR, config.MULTI_MODEL, config.GIGAAM_QUANTIZATION)

def is_vad_downloaded():
    folder = Path(config.VAD_DIR)
    if not folder.is_dir():
        return False
    names = ("silero_vad.onnx", "silero_vad.int8.onnx", "model.onnx", "model_int8.onnx")
    return any(path.is_file() and path.stat().st_size and path.name in names for path in folder.rglob("*.onnx"))

def _onnx_model_ready(target_dir, model_name, quant):
    folder = Path(target_dir)
    if not folder.is_dir():
        return False
    model = re.fullmatch(r"gigaam-v[23](-e2e)?-(ctc|rnnt)", model_name.lower())
    if model:
        suffix = "" if quant in ("", "float32") else "?" + quant
        e2e, architecture = model.groups()
        prefix = "v3_e2e" if e2e else "v?"
        stem = f"{prefix}_{architecture}"
        patterns = ([f"{stem}{suffix}.onnx"] if architecture == "ctc" else
                    [f"{stem}_{part}{suffix}.onnx" for part in ("encoder", "decoder", "joint")])
        patterns.append(f"{stem}_vocab.txt" if e2e else "v?_vocab.txt")
        for pattern in patterns:
            matches = list(folder.glob(pattern))
            if not matches and pattern.endswith(".onnx"):
                matches = list(folder.glob(pattern[:-5] + ".ort"))
            if len(matches) != 1 or not matches[0].is_file() or not matches[0].stat().st_size:
                return False
        return True
    # Parakeet and other custom models: one non-empty weight file is enough.
    return any(path.is_file() and path.stat().st_size and
               (("int8" in path.name) == (quant == "int8"))
               for path in folder.glob("*.onnx"))

def download_whisper_direct(whisper_model):
    repo_id = WHISPER_REPOS.get(whisper_model.lower(), whisper_model)
    if not repo_id:
        raise ValueError(f"Unknown Whisper model: {whisper_model}")
    target_dir = config.WHISPER_MODEL_PATH if config.WHISPER_MODEL_PATH else config.WHISPER_DIR
    os.makedirs(target_dir, exist_ok=True)
    
    print(f"\nDownloading Whisper ({whisper_model}) directly into {target_dir}...")
    snapshot_download(
        repo_id=repo_id,
        local_dir=target_dir
    )

def download_gigaam_direct(gigaam_model, quant="int8"):
    repo_id = "istupakov/gigaam-v3-onnx"
    target_dir = config.GIGAAM_MODEL_PATH if config.GIGAAM_MODEL_PATH else config.GIGAAM_DIR
    os.makedirs(target_dir, exist_ok=True)

    q_str = f" ({quant})" if quant else ""
    print(f"\nDownloading GigaAM ({gigaam_model}{q_str}) directly into {target_dir}...")

    patterns = ["*.json", "*.txt"]
    if quant == "int8":
        patterns.append("*int8*")
    else:
        patterns.append("*.onnx")

    snapshot_download(
        repo_id=repo_id,
        local_dir=target_dir,
        allow_patterns=patterns
    )

def download_parakeet_direct(model_name, quant="int8"):
    repo_id = "istupakov/parakeet-tdt-0.6b-v3-onnx"
    target_dir = config.PARAKEET_DIR
    os.makedirs(target_dir, exist_ok=True)
    q_str = f" ({quant})" if quant else ""
    print(f"\nDownloading Parakeet ({model_name}{q_str}) directly into {target_dir}...")
    patterns = ["*.json", "*.txt"]
    patterns.append("*int8*" if quant == "int8" else "*.onnx")
    snapshot_download(
        repo_id=repo_id,
        local_dir=target_dir,
        allow_patterns=patterns
    )

def download_vad_direct():
    target_dir = config.VAD_DIR
    os.makedirs(target_dir, exist_ok=True)
    print(f"\nDownloading pause detection (silero) directly into {target_dir}...")
    snapshot_download(
        repo_id="onnx-community/silero-vad",
        local_dir=target_dir,
        allow_patterns=["*.onnx", "*.json"]
    )

def _ask_download(label, folder):
    print("\n" + "=" * 65)
    print("The model selected in config.ini is not downloaded")
    print(f"Engine: {label}")
    print(f"Folder: {folder}")
    print("Downloading does not change config.ini.")
    print("=" * 65)
    answer = input("Download this model? (y/n): ").strip().lower()
    return answer in ("y", "yes")

def ensure_configured_model():
    """Download the models selected in config.ini. Does not change settings.

    ru needs the model in ru_recognition_model. multi needs the Parakeet or
    Whisper model in multi_recognition_model. ONNX models also need the pause detector.
    """
    jobs = [("gigaam", f"GigaAM ({config.GIGAAM_MODEL}, {config.GIGAAM_QUANTIZATION})",
             config.GIGAAM_DIR, is_gigaam_downloaded())]
    if config.RECOGNITION_MODE == "multi":
        if config.MULTI_ENGINE == "whisper":
            jobs.append(("whisper", f"Whisper ({config.WHISPER_MODEL})", config.WHISPER_DIR, is_whisper_downloaded()))
        elif config.MULTI_ENGINE == "parakeet":
            jobs.append(("parakeet", f"Parakeet ({config.MULTI_MODEL}, {config.GIGAAM_QUANTIZATION})",
                         config.PARAKEET_DIR, is_parakeet_downloaded()))
        else:
            print(f"\nconfig.ini selects an unknown speech model \"{config.STT_ENGINE}\". Use a GigaAM name for ru_recognition_model and a Whisper or Parakeet name for multi_recognition_model.")
            sys.exit(1)
    elif config.STT_ENGINE not in ("gigaam", "whisper", "parakeet"):
        print(f"\nconfig.ini selects an unknown speech model \"{config.STT_ENGINE}\". Use a GigaAM name for ru_recognition_model and a Whisper or Parakeet name for multi_recognition_model.")
        sys.exit(1)
    if any(engine != "whisper" for engine, _label, _folder, _ready in jobs):
        jobs.append(("vad", "pause detection (silero)", config.VAD_DIR, is_vad_downloaded()))

    missing = [job for job in jobs if not job[3]]
    if not missing:
        return

    for engine, label, folder, _ready in missing:
        if not _ask_download(label, folder):
            print("Download cancelled. Edit [Recognition] in config/config.ini and start again.")
            sys.exit(0)
        if engine == "whisper":
            download_whisper_direct(config.WHISPER_MODEL)
        elif engine == "parakeet":
            download_parakeet_direct(config.MULTI_MODEL, quant=config.GIGAAM_QUANTIZATION)
        elif engine == "vad":
            download_vad_direct()
        else:
            download_gigaam_direct(config.GIGAAM_MODEL, quant=config.GIGAAM_QUANTIZATION)
    print("\n[OK] Model downloaded into models/.\n")
