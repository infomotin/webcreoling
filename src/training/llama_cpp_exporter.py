"""
llama.cpp & GGUF Integration Utilities.
Prepares model weights, configuration, and tokenizers for GGUF quantization and llama.cpp execution.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from config.settings import settings
from src.common.logger import get_logger
from src.common.utils import safe_write_json

logger = get_logger("webcreoling.training.llama_cpp")


class LlamaCppExporter:
    """Manages llama.cpp export configs, GGUF conversion instructions, and quantization flags."""

    def __init__(self, checkpoint_dir: Optional[Path] = None):
        self.checkpoint_dir = checkpoint_dir or (settings.CHECKPOINTS_DIR / "final_specialized_model")

    def create_llama_cpp_manifest(self, output_path: Optional[Path] = None) -> Path:
        """
        Generate export metadata and step-by-step conversion manifest for llama.cpp GGUF.
        """
        target_path = output_path or (self.checkpoint_dir / "llama_cpp_manifest.json")
        manifest = {
            "model_type": "causal_lm",
            "base_checkpoint_dir": str(self.checkpoint_dir),
            "suggested_quantization": ["Q4_K_M", "Q5_K_M", "Q8_0"],
            "conversion_command": (
                f"python llama.cpp/convert_hf_to_gguf.py {self.checkpoint_dir} "
                f"--outfile {self.checkpoint_dir / 'model-q4_k_m.gguf'} --outtype q8_0"
            ),
            "cpp_runtime_example": (
                f"./llama-cli -m {self.checkpoint_dir / 'model-q4_k_m.gguf'} "
                f"-p 'শিরোনাম: ' -n 128 -c 512"
            ),
        }
        safe_write_json(target_path, manifest)
        logger.info(f"llama.cpp manifest saved to {target_path}")
        return target_path
