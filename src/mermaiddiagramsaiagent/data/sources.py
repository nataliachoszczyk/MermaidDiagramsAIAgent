"""Single place that defines the raw public datasets and where they live on disk."""

from dataclasses import dataclass
from pathlib import Path

RAW_DIR = Path("data/raw")


@dataclass(frozen=True)
class Source:
    repo_id: str
    local_name: str
    revision: str 
    allow_patterns: tuple[str, ...]  # which repo files to download

    @property
    def local_dir(self) -> Path:
        return RAW_DIR / self.local_name


RONNIEALLEN = Source(
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
)

MERMAIDSEQBENCH = Source(
    repo_id="ibm-research/MermaidSeqBench",
    local_name="mermaidseqbench",
    revision="c1547591b9f95b3b7a9a5041dfce88185429ce33",
    allow_patterns=("README.md", "data.csv"),
)

SOURCES: tuple[Source, ...] = (RONNIEALLEN, MERMAIDSEQBENCH)
