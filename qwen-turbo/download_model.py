from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="Qwen/Qwen-Image-2.1-Turbo",
    revision="fc13ba1986fcb905854dc8de2f52eee395f49b5b",
    local_dir="/opt/qwen-image-21-turbo",
    ignore_patterns=["assets/*", ".gitattributes"],
    max_workers=4,
)
