import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from deepeval.synthesizer import Evolution, Synthesizer
from deepeval.synthesizer.config import (
    EvolutionConfig,
    FiltrationConfig,
    StylingConfig,
)
TABULAR_EXTENSIONS = {".csv", ".xls", ".xlsx"}

# ---------------------------------------------------------------------------
# Edit these variables directly before running the script.
# ---------------------------------------------------------------------------
MODEL = "gpt-5-mini"
INPUT_DIR = Path("eval/knowledgebase").resolve()
INPUT_FILES: list[str] = []
SAMPLE_COUNT = 60
QUESTION_COMPLEXITY = "simple"  # simple | medium | complex
ANSWER_STYLE = "short"  # short | medium | detailed
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
CHUNKS_PER_CONTEXT = 2 # how many chunks to bundle together as a single context for QA generation
MAX_CONTEXTS: int | None = 500
OUTPUT_DIR = Path("eval/dataset").resolve()
OUTPUT_NAME = "testset"
CONTEXT_BATCH_SIZE = 25


@dataclass(frozen=True)
class ComplexityProfile:
    num_evolutions: int
    evolutions: dict[Evolution, float]
    max_goldens_per_context: int


COMPLEXITY_PROFILES: dict[str, ComplexityProfile] = {
    "simple": ComplexityProfile(
        num_evolutions=1,
        evolutions={
            Evolution.CONCRETIZING: 0.7,
            Evolution.CONSTRAINED: 0.3,
        },
        max_goldens_per_context=1,
    ),
    "medium": ComplexityProfile(
        num_evolutions=2,
        evolutions={
            Evolution.REASONING: 0.35,
            Evolution.CONCRETIZING: 0.25,
            Evolution.CONSTRAINED: 0.2,
            Evolution.COMPARATIVE: 0.2,
        },
        max_goldens_per_context=2,
    ),
    "complex": ComplexityProfile(
        num_evolutions=3,
        evolutions={
            Evolution.REASONING: 0.25,
            Evolution.MULTICONTEXT: 0.2,
            Evolution.COMPARATIVE: 0.2,
            Evolution.HYPOTHETICAL: 0.15,
            Evolution.CONSTRAINED: 0.1,
            Evolution.IN_BREADTH: 0.1,
        },
        max_goldens_per_context=3,
    ),
}


def resolve_input_files(input_dir: Path, files: list[str]) -> list[Path]:
    resolved: list[Path] = []

    for raw_path in files:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (input_dir / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if candidate.is_file():
            resolved.append(candidate)
        else:
            raise FileNotFoundError(f"Input file not found: {candidate}")

    if not resolved:
        resolved = [
            path.resolve()
            for path in sorted(input_dir.iterdir())
            if path.is_file()
        ]

    deduped: dict[Path, None] = {}
    for path in resolved:
        deduped[path] = None

    return sorted(deduped)


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def dataframe_to_text(df: pd.DataFrame, *, title: str) -> str:
    cleaned = df.fillna("").astype(str)
    lines = [title]
    for row_index, row in cleaned.iterrows():
        values = [f"{column}: {value.strip()}" for column, value in row.items() if value.strip()]
        if values:
            lines.append(f"Row {row_index + 1}: " + " | ".join(values))
    return "\n".join(lines)


def read_spreadsheet(path: Path) -> str:
    workbook = pd.read_excel(path, sheet_name=None)
    sections: list[str] = []
    for sheet_name, df in workbook.items():
        if df.empty:
            continue
        sections.append(
            dataframe_to_text(df, title=f"Workbook: {path.name}\nSheet: {sheet_name}")
        )
    return "\n\n".join(sections)


def read_csv(path: Path) -> str:
    df = pd.read_csv(path)
    return dataframe_to_text(df, title=f"CSV: {path.name}")


def load_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return read_spreadsheet(path)
    if suffix == ".csv":
        return read_csv(path)
    raise ValueError(
        f"Unsupported context-only file type: {path}. "
        "Tabular parsing is only used for .csv, .xls, and .xlsx files."
    )


def chunk_text(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if chunk_size <= 0:
        raise ValueError("--chunk-size must be greater than 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("--chunk-overlap must be smaller than --chunk-size")

    chunks: list[str] = []
    start = 0
    step = chunk_size - chunk_overlap
    while start < len(normalized):
        chunk = normalized[start:start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def build_contexts_for_file(
    path: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
    chunks_per_context: int,
) -> list[list[str]]:
    source_text = load_document_text(path)
    chunks = chunk_text(
        source_text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    contexts: list[list[str]] = []
    for index in range(0, len(chunks), max(chunks_per_context, 1)):
        bundle = chunks[index:index + max(chunks_per_context, 1)]
        if bundle:
            contexts.append(bundle)
    return contexts


def build_generation_instruction(answer_style: str) -> str:
    answer_instruction = {
        "short": "Answers must be factual, direct, and usually 1 sentence.",
        "medium": "Answers must be factual, clear, and usually 1 to 3 sentences.",
        "detailed": "Answers must be factual, complete, and still avoid unnecessary filler.",
    }[answer_style]
    return (
        "Generate realistic questions that can be answered strictly from the provided context. "
        "Prefer concrete, domain-grounded wording over vague or generic prompts. "
        f"{answer_instruction} "
        "Do not invent facts that are not explicitly supported by the context."
    )


def serialize_context(context: list[str]) -> str:
    return json.dumps(context, ensure_ascii=False)


def golden_to_record(golden) -> dict:
    context = golden.context or []
    return {
        "user_input": golden.input,
        "reference": golden.expected_output or "",
        "reference_contexts": serialize_context(context),
        "source_file": golden.source_file or "",
        "context_chunk_count": len(context),
        "actual_output": golden.actual_output or "",
    }


def build_output_rows(
    generated_records: Iterable[dict],
    *,
    complexity: str,
    answer_style: str,
) -> list[dict]:
    rows: list[dict] = []
    for index, record in enumerate(generated_records, start=1):
        rows.append(
            {
                "sample_id": f"synthetic_{index:04d}",
                "user_input": record["user_input"],
                "reference": record["reference"],
                "reference_contexts": record["reference_contexts"],
                "source_file": record["source_file"],
                "synthesizer_name": "deepeval_answerable",
                "question_complexity": complexity,
                "answer_style": answer_style,
                "context_chunk_count": record["context_chunk_count"],
                "actual_output": record["actual_output"],
            }
        )
    return rows


def dedupe_records(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (
            record.get("user_input", ""),
            record.get("source_file", ""),
            record.get("reference_contexts", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {
            "doc_files_completed": [],
            "tabular_batches_completed": {},
            "tabular_contexts_counted": [],
            "generated_records": [],
            "contexts_built": 0,
        }
    with path.open("r", encoding="utf-8") as handle:
        checkpoint = json.load(handle)
    checkpoint.setdefault("doc_files_completed", [])
    checkpoint.setdefault("tabular_batches_completed", {})
    checkpoint.setdefault("tabular_contexts_counted", [])
    checkpoint.setdefault("generated_records", [])
    checkpoint.setdefault("contexts_built", 0)
    checkpoint["generated_records"] = dedupe_records(checkpoint["generated_records"])
    return checkpoint


def save_checkpoint(path: Path, checkpoint: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(checkpoint, handle, indent=2, ensure_ascii=False)


def write_dataset_outputs(
    *,
    output_dir: Path,
    base_name: str,
    generated_records: list[dict],
    complexity: str,
    answer_style: str,
) -> tuple[Path, Path]:
    rows = build_output_rows(
        generated_records,
        complexity=complexity,
        answer_style=answer_style,
    )
    df = pd.DataFrame(rows)
    csv_path = output_dir / f"{base_name}.csv"
    jsonl_path = output_dir / f"{base_name}.jsonl"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return csv_path, jsonl_path


def chunked(items: list[list[str]], size: int) -> Iterable[tuple[int, list[list[str]]]]:
    if size <= 0:
        raise ValueError("CONTEXT_BATCH_SIZE must be greater than 0")
    for index in range(0, len(items), size):
        yield index // size, items[index:index + size]


def split_input_files(files: list[Path]) -> tuple[list[Path], list[Path]]:
    doc_files: list[Path] = []
    tabular_files: list[Path] = []
    for path in files:
        suffix = path.suffix.lower()
        if suffix in TABULAR_EXTENSIONS:
            tabular_files.append(path)
        else:
            doc_files.append(path)
    return doc_files, tabular_files


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY in the environment before running.")
    os.environ["OPENAI_API_KEY"] = api_key

    if QUESTION_COMPLEXITY not in COMPLEXITY_PROFILES:
        raise ValueError(
            f"QUESTION_COMPLEXITY must be one of {sorted(COMPLEXITY_PROFILES)}"
        )
    if ANSWER_STYLE not in {"short", "medium", "detailed"}:
        raise ValueError("ANSWER_STYLE must be one of: short, medium, detailed")
    if SAMPLE_COUNT <= 0:
        raise ValueError("SAMPLE_COUNT must be greater than 0")

    files = resolve_input_files(INPUT_DIR.resolve(), INPUT_FILES)
    if not files:
        raise RuntimeError("No input files were found.")
    doc_files, tabular_files = split_input_files(files)

    profile = COMPLEXITY_PROFILES[QUESTION_COMPLEXITY]
    output_dir = OUTPUT_DIR.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = OUTPUT_NAME.strip() or "testset"
    checkpoint_path = output_dir / f"{base_name}.checkpoint.json"
    checkpoint = load_checkpoint(checkpoint_path)
    generated_records: list[dict] = checkpoint["generated_records"]
    contexts_built = int(checkpoint["contexts_built"])

    print(f"Using model: {MODEL}")
    print(f"Using critic model: {MODEL}")
    print(f"Generating {SAMPLE_COUNT} samples from {len(files)} file(s).")
    print(f"Checkpoint: {checkpoint_path}")
    for path in files:
        print(f"  - {path}")

    synthesizer = Synthesizer(
        model=MODEL,
        async_mode=True,
        filtration_config=FiltrationConfig(critic_model=MODEL),
        evolution_config=EvolutionConfig(
            num_evolutions=profile.num_evolutions,
            evolutions=profile.evolutions,
        ),
        styling_config=StylingConfig(
            task=build_generation_instruction(ANSWER_STYLE),
            expected_output_format="Return a factual reference answer only.",
        ),
    )

    if doc_files:
        print(f"Generating from {len(doc_files)} file(s) via DeepEval document parsing...")
        completed_doc_files = set(checkpoint["doc_files_completed"])
        for path in doc_files:
            path_key = str(path)
            if path_key in completed_doc_files:
                print(f"Skipping completed doc file: {path.name}")
                continue
            goldens = synthesizer.generate_goldens_from_docs(
                document_paths=[path_key],
                include_expected_output=True,
                max_goldens_per_context=profile.max_goldens_per_context,
            )
            generated_records.extend(golden_to_record(golden) for golden in goldens)
            generated_records = dedupe_records(generated_records)
            checkpoint["generated_records"] = generated_records
            checkpoint["doc_files_completed"].append(path_key)
            save_checkpoint(checkpoint_path, checkpoint)
            write_dataset_outputs(
                output_dir=output_dir,
                base_name=base_name,
                generated_records=generated_records[:SAMPLE_COUNT],
                complexity=QUESTION_COMPLEXITY,
                answer_style=ANSWER_STYLE,
            )

    if tabular_files:
        tabular_batches_completed: dict[str, list[int]] = checkpoint["tabular_batches_completed"]
        tabular_contexts_counted = set(checkpoint["tabular_contexts_counted"])
        for path in tabular_files:
            file_contexts = build_contexts_for_file(
                path,
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                chunks_per_context=CHUNKS_PER_CONTEXT,
            )
            if MAX_CONTEXTS is not None:
                file_contexts = file_contexts[:MAX_CONTEXTS]
            path_key = str(path)
            if path_key not in tabular_contexts_counted:
                contexts_built += len(file_contexts)
                checkpoint["contexts_built"] = contexts_built
                checkpoint["tabular_contexts_counted"].append(path_key)
                tabular_contexts_counted.add(path_key)
            completed_batches = set(tabular_batches_completed.get(str(path), []))
            print(
                f"Generating from tabular file {path.name} "
                f"using {len(file_contexts)} prepared context(s)..."
            )
            for batch_index, context_batch in chunked(file_contexts, CONTEXT_BATCH_SIZE):
                if batch_index in completed_batches:
                    print(f"Skipping completed batch {batch_index + 1} for {path.name}")
                    continue
                source_files = [path.name] * len(context_batch)
                goldens = synthesizer.generate_goldens_from_contexts(
                    contexts=context_batch,
                    include_expected_output=True,
                    max_goldens_per_context=profile.max_goldens_per_context,
                    source_files=source_files,
                )
                generated_records.extend(golden_to_record(golden) for golden in goldens)
                generated_records = dedupe_records(generated_records)
                checkpoint["generated_records"] = generated_records
                tabular_batches_completed.setdefault(str(path), []).append(batch_index)
                checkpoint["tabular_batches_completed"] = tabular_batches_completed
                save_checkpoint(checkpoint_path, checkpoint)
                write_dataset_outputs(
                    output_dir=output_dir,
                    base_name=base_name,
                    generated_records=generated_records[:SAMPLE_COUNT],
                    complexity=QUESTION_COMPLEXITY,
                    answer_style=ANSWER_STYLE,
                )

    if doc_files:
        print("DeepEval handled context extraction for non-tabular files directly.")
    if tabular_files:
        print(f"Built {contexts_built} retrieval context(s) from tabular files.")
    if not generated_records:
        raise RuntimeError("DeepEval did not return any synthetic samples.")

    rows = build_output_rows(
        generated_records[:SAMPLE_COUNT],
        complexity=QUESTION_COMPLEXITY,
        answer_style=ANSWER_STYLE,
    )
    if len(rows) < SAMPLE_COUNT:
        print(
            "Warning: generated fewer samples than requested. "
            f"Requested={SAMPLE_COUNT}, generated={len(rows)}."
        )
    csv_path, jsonl_path = write_dataset_outputs(
        output_dir=output_dir,
        base_name=base_name,
        generated_records=generated_records[:SAMPLE_COUNT],
        complexity=QUESTION_COMPLEXITY,
        answer_style=ANSWER_STYLE,
    )

    manifest = {
        "model": MODEL,
        "sample_count": len(rows),
        "requested_sample_count": SAMPLE_COUNT,
        "complexity": QUESTION_COMPLEXITY,
        "answer_style": ANSWER_STYLE,
        "files": [str(path) for path in files],
        "contexts_built": contexts_built,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "chunks_per_context": CHUNKS_PER_CONTEXT,
        "context_batch_size": CONTEXT_BATCH_SIZE,
        "checkpoint_path": str(checkpoint_path),
        "output_csv": str(csv_path),
        "output_jsonl": str(jsonl_path),
    }
    manifest_path = output_dir / f"{base_name}.manifest.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)

    checkpoint["generated_records"] = generated_records
    checkpoint["contexts_built"] = contexts_built
    save_checkpoint(checkpoint_path, checkpoint)

    print(f"Saved CSV: {csv_path}")
    print(f"Saved JSONL: {jsonl_path}")
    print(f"Saved manifest: {manifest_path}")


if __name__ == "__main__":
    main()
