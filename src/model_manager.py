import os
import sys

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

def ensure_configured_model():
    """Download the Whisper model named in config.ini. Does not change settings."""
    ready = is_whisper_downloaded()
    label = f"Whisper ({config.WHISPER_MODEL})"

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

    download_whisper_direct(config.WHISPER_MODEL)
    print("\n[OK] Model downloaded into models/.\n")
