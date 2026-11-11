"""Download the raw public datasets used for the golden set into data/raw/.

Revisions are pinned so that every time we get byte-identical files.
"""

from pathlib import Path

from huggingface_hub import snapshot_download

from mermaiddiagramsaiagent.data.sources import SOURCES, Source


def download_source(source: Source) -> Path:
    snapshot_download(
        repo_id=source.repo_id,
        repo_type="dataset",
        revision=source.revision,
        allow_patterns=list(source.allow_patterns),
        local_dir=source.local_dir,
    )
    return source.local_dir


def main() -> None:
    for source in SOURCES:
        target = download_source(source)
        print(f"{source.repo_id}@{source.revision[:8]} -> {target}")


if __name__ == "__main__":
    main()
