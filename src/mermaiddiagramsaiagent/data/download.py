"""Download the raw public datasets used for the golden set into data/raw/.

Revisions are pinned so that every time we get byte-identical files.
"""

from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import snapshot_download

RAW_DIR = Path("data/raw")


@dataclass(frozen=True)
class Source:
    repo_id: str
    local_name: str
    revision: str
    allow_patterns: tuple[str, ...]


SOURCES: tuple[Source, ...] = (
    Source(
        repo_id="RonnieAllen/mermaid-flowchart-dataset",
        local_name="ronnieallen",
        revision="d28ea0de0893de7b6d2259e7bbcb993061637075",
        allow_patterns=(
            "README.md",
            "LICENSE",
            "data/*.jsonl",
            "dataset_infos.json",
            "statistics.json",
            "quality_report.json",
            "validation_report.json",
        ),
    ),
    Source(
        repo_id="ibm-research/MermaidSeqBench",
        local_name="mermaidseqbench",
        revision="c1547591b9f95b3b7a9a5041dfce88185429ce33",
        allow_patterns=("README.md", "data.csv"),
    ),
)

def download_source(source: Source, raw_dir: Path) -> Path:
    target = raw_dir / source.local_name
    snapshot_download(
        repo_id=source.repo_id,
        repo_type="dataset",
        revision=source.revision,
        allow_patterns=list(source.allow_patterns),
        local_dir=target,
    )
    return target


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        target = download_source(source, RAW_DIR)
        print(f"{source.repo_id}@{source.revision[:8]} -> {target}")


if __name__ == "__main__":
    main()
