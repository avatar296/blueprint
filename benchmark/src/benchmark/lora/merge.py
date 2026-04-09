"""Merge LoRA adapter into base model and export as GGUF for Ollama."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def merge_and_export_gguf(
    base_model: str,
    adapter_path: str,
    output_dir: str = "benchmark/merged_models",
    quant_levels: list[str] | None = None,
    ollama_model_name: str = "llama3-kyb-lora",
) -> list[str]:
    """Merge LoRA adapter into base weights, export GGUF, register with Ollama.

    Steps:
        1. Load base + adapter via PEFT, merge_and_unload()
        2. Save merged HF model
        3. Convert to GGUF via llama.cpp's convert_hf_to_gguf.py
        4. Quantize at each target level
        5. Register with Ollama via ``ollama create``

    Args:
        base_model: HuggingFace model ID.
        adapter_path: Path to saved LoRA adapter directory.
        output_dir: Where to save merged models and GGUF files.
        quant_levels: GGUF quantization levels (default: f16, q8_0, q4_0).
        ollama_model_name: Base name for Ollama model tags.

    Returns:
        List of Ollama model tags created.
    """
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if quant_levels is None:
        quant_levels = ["f16", "q8_0", "q4_0"]

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Load and merge.
    log.info("Loading base model: %s", base_model)
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForCausalLM.from_pretrained(
        base_model, device_map="auto", torch_dtype="auto",
    )

    log.info("Loading adapter: %s", adapter_path)
    model = PeftModel.from_pretrained(model, adapter_path)

    log.info("Merging adapter into base weights...")
    model = model.merge_and_unload()

    # 2. Save merged HF model.
    merged_path = out / "merged_hf"
    log.info("Saving merged model to %s", merged_path)
    model.save_pretrained(str(merged_path))
    tokenizer.save_pretrained(str(merged_path))

    # 3-5. Convert and quantize.
    created_tags: list[str] = []
    for level in quant_levels:
        tag = _convert_and_register(
            merged_path, level, ollama_model_name, out,
        )
        if tag:
            created_tags.append(tag)

    return created_tags


def _convert_and_register(
    merged_path: Path,
    quant_level: str,
    model_name: str,
    output_dir: Path,
) -> str | None:
    """Convert merged model to GGUF at a specific quant level and register with Ollama.

    Uses llama-cpp-python's built-in conversion utilities if available,
    otherwise falls back to calling llama.cpp CLI tools.
    """
    gguf_filename = f"{model_name}-{quant_level}.gguf"
    gguf_path = output_dir / gguf_filename

    # Map our quant names to llama.cpp quantization types.
    llama_cpp_quant_map = {
        "f16": "f16",
        "q8_0": "q8_0",
        "q4_0": "q4_0",
        "q4_k_m": "q4_k_m",
        "q5_k_m": "q5_k_m",
    }
    quant_type = llama_cpp_quant_map.get(quant_level, quant_level)

    # Try convert_hf_to_gguf.py (ships with llama.cpp).
    try:
        log.info("Converting to GGUF (%s): %s -> %s", quant_level, merged_path, gguf_path)

        # First convert to f16 GGUF.
        f16_path = output_dir / f"{model_name}-f16.gguf"
        if not f16_path.exists():
            subprocess.run(
                [
                    "python", "-m", "llama_cpp.convert",
                    str(merged_path),
                    "--outfile", str(f16_path),
                    "--outtype", "f16",
                ],
                check=True,
                capture_output=True,
            )

        # Quantize if not f16.
        if quant_level != "f16":
            subprocess.run(
                [
                    "llama-quantize",
                    str(f16_path),
                    str(gguf_path),
                    quant_type,
                ],
                check=True,
                capture_output=True,
            )
        else:
            gguf_path = f16_path

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.warning(
            "GGUF conversion failed for %s — you may need to install llama.cpp tools. "
            "Error: %s",
            quant_level, e,
        )
        return None

    # Register with Ollama.
    tag = f"{model_name}:8b-{quant_level}" if quant_level != "f16" else f"{model_name}:8b"
    modelfile_content = f"FROM {gguf_path}\n"
    modelfile_path = output_dir / f"Modelfile.{quant_level}"
    modelfile_path.write_text(modelfile_content)

    try:
        log.info("Registering with Ollama as %s", tag)
        subprocess.run(
            ["ollama", "create", tag, "-f", str(modelfile_path)],
            check=True,
            capture_output=True,
        )
        log.info("Registered Ollama model: %s", tag)
        return tag
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.warning("Ollama registration failed for %s: %s", tag, e)
        # Return the tag anyway — user can manually register.
        return tag
