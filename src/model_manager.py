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
    folder = Path(target_dir)
    if not folder.is_dir():
        return False
    quant = config.GIGAAM_QUANTIZATION
    suffix = "" if quant in ("", "float32") else "?" + quant
    # Match the file patterns used by onnx-asr for the supported GigaAM versions.
    model = re.fullmatch(r"gigaam-v[23](-e2e)?-(ctc|rnnt)", config.GIGAAM_MODEL.lower())
    if model:
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
    # Preserve custom-model support while distinguishing full and compressed files.
    return any(path.is_file() and path.stat().st_size and
               (("int8" in path.name) == (quant == "int8"))
               for path in folder.glob("*.onnx"))

def download_whisper_direct(whisper_model):
    repo_id = WHISPER_REPOS.get(whisper_model.lower(), whisper_model)
    target_dir = config.WHISPER_MODEL_PATH if config.WHISPER_MODEL_PATH else config.WHISPER_DIR
    os.makedirs(target_dir, exist_ok=True)
    
    print(f"\nDownloading Whisper ({whisper_model}) directly into {target_dir}...")
    snapshot_download(
        repo_id=repo_id,
        local_dir=target_dir,
        local_dir_use_symlinks=False
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
        allow_patterns=patterns,
        local_dir_use_symlinks=False
    )

def ensure_configured_model():
    """Download the engine selected in config.ini. Does not change settings."""
    engine = config.STT_ENGINE.lower()

    if engine == "whisper":
        ready = is_whisper_downloaded()
        label = f"Whisper ({config.WHISPER_MODEL})"
    elif engine == "gigaam":
        ready = is_gigaam_downloaded()
        label = f"GigaAM ({config.GIGAAM_MODEL}, {config.GIGAAM_QUANTIZATION})"
    else:
        print(f"\nconfig.ini selects an unknown speech model \"{config.STT_ENGINE}\". Use a Whisper name or gigaam-v3-e2e-rnnt.")
        sys.exit(1)

    if ready:
        return

    print("\n" + "=" * 65)
    print("The model selected in config.ini is not downloaded")
    print(f"Engine: {label}")
    print(f"Folder: {config.MODELS_DIR}")
    print("Downloading does not change config.ini.")
    prompt = "Download this model? (y/n): "
    decline = "Download cancelled. Edit [Recognition] in config/config.ini and start again."
    print("=" * 65)
    answer = input(prompt).strip().lower()
    if answer not in ("y", "yes"):
        print(decline)
        sys.exit(0)

    if engine == "whisper":
        download_whisper_direct(config.WHISPER_MODEL)
    else:
        download_gigaam_direct(config.GIGAAM_MODEL, quant=config.GIGAAM_QUANTIZATION)
    print("\n[OK] Model downloaded into models/.\n")
