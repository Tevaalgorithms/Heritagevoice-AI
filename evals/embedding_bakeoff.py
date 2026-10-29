"""Run the embedding bake-off against Pinecone Inference and save a JSON report.

    PINECONE_API_KEY=... uv run python -m evals.embedding_bakeoff multilingual-e5-large

Reports go to evals/results/ (git-ignored). Run it once per candidate model, compare the Tamil
and cross-language rows, then set HERITAGEVOICE_EMBEDDING_MODEL and the index dimension.
"""

import json
import sys
from pathlib import Path

from pinecone import Pinecone

from app.adapters.pinecone_store import PineconeEmbedder
from app.config import Settings
from app.evaluation import evaluate, load_fixtures

ROOT = Path(__file__).resolve().parent
EXPECTED_ARGS = 2  # the script name and the model


def main(argv: list[str]) -> int:
    settings = Settings()
    if settings.pinecone_api_key is None or len(argv) != EXPECTED_ARGS:
        print("Usage: PINECONE_API_KEY=... python -m evals.embedding_bakeoff <model>")
        return 2
    model = argv[1]
    embedder = PineconeEmbedder(
        Pinecone(api_key=settings.pinecone_api_key.get_secret_value()), model
    )
    recordings, questions = load_fixtures(ROOT / "fixtures")
    report = {"model": model, **evaluate(embedder, recordings, questions)}
    out = ROOT / "results" / f"embedding_bakeoff_{model}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
