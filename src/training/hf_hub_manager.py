"""
Hugging Face Hub Integration Manager.
Supports downloading lightweight AI models, caching, and exporting/pushing trained LoRA models to Hugging Face Hub.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import os
import json
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
from huggingface_hub import HfApi, create_repo, upload_folder
from config.settings import settings
from src.common.logger import get_logger

logger = get_logger("webcreoling.training.hf_hub_manager")

RECOMMENDED_LIGHTWEIGHT_MODELS = [
    {
        "id": "HuggingFaceTB/SmolLM2-135M",
        "name": "SmolLM2 135M",
        "params": "135 Million",
        "size_mb": 270,
        "description": "Ultra-lightweight state-of-the-art small LM, ultra-fast on CPU.",
        "recommended": True,
    },
    {
        "id": "HuggingFaceTB/SmolLM2-360M",
        "name": "SmolLM2 360M",
        "params": "360 Million",
        "size_mb": 720,
        "description": "Strong lightweight reasoning and language understanding on CPU.",
        "recommended": True,
    },
    {
        "id": "Qwen/Qwen2.5-0.5B",
        "name": "Qwen 2.5 0.5B",
        "params": "490 Million",
        "size_mb": 980,
        "description": "Excellent Asian/Bengali script understanding and JSON extraction.",
        "recommended": True,
    },
    {
        "id": "distilbert/distilgpt2",
        "name": "DistilGPT-2",
        "params": "82 Million",
        "size_mb": 320,
        "description": "Standard baseline model for rapid local debugging and testing.",
        "recommended": False,
    },
    {
        "id": "google/gemma-2-2b",
        "name": "Gemma 2 2B",
        "params": "2.0 Billion",
        "size_mb": 4200,
        "description": "High-capability Google architecture for production deployments.",
        "recommended": False,
    },
]


class HuggingFaceHubManager:
    """Manages Hugging Face model downloads, cache inspection, and hub deployments."""

    @classmethod
    def get_recommended_models(cls) -> List[Dict[str, Any]]:
        """Return list of recommended lightweight LLMs."""
        return RECOMMENDED_LIGHTWEIGHT_MODELS

    @classmethod
    def download_model(cls, model_id: str, token: Optional[str] = None) -> Dict[str, Any]:
        """
        Download and cache tokenizer and model weights from Hugging Face Hub.
        """
        logger.info(f"Downloading model '{model_id}' from Hugging Face Hub...")
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_id, token=token)
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                token=token,
                low_cpu_mem_usage=True,
            )

            cache_target = settings.CHECKPOINTS_DIR / "downloaded_models" / model_id.replace("/", "_")
            cache_target.mkdir(parents=True, exist_ok=True)

            tokenizer.save_pretrained(str(cache_target))
            model.save_pretrained(str(cache_target))

            num_params = sum(p.numel() for p in model.parameters())

            logger.info(f"Successfully downloaded and cached '{model_id}' ({num_params:,} parameters).")
            return {
                "status": "success",
                "model_id": model_id,
                "cached_path": str(cache_target),
                "param_count": num_params,
                "vocab_size": len(tokenizer),
            }
        except Exception as e:
            logger.error(f"Failed to download '{model_id}' from Hugging Face Hub: {e}")
            raise e

    @classmethod
    def export_and_push_to_hub(
        cls,
        checkpoint_dir: Path,
        repo_id: str,
        hf_token: str,
        private: bool = False,
        base_model_name: Optional[str] = None,
        tasks: Optional[List[str]] = None,
        eval_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Upload LoRA adapter or fine-tuned model checkpoint to Hugging Face Hub with an auto-generated Model Card.
        """
        if not hf_token or not repo_id:
            raise ValueError("Hugging Face API Token and Repo ID (e.g. 'username/model-name') are required.")

        logger.info(f"Preparing to upload checkpoint from {checkpoint_dir} to Hugging Face Hub '{repo_id}'...")

        api = HfApi(token=hf_token)
        create_repo(
            repo_id=repo_id,
            token=hf_token,
            private=private,
            exist_ok=True,
            repo_type="model",
        )

        # Generate automated Model Card (README.md)
        model_card_content = cls._generate_model_card(
            repo_id=repo_id,
            base_model_name=base_model_name or settings.BASE_MODEL_NAME,
            tasks=tasks or ["categorization", "headline_generation", "summarization", "ner"],
            eval_metrics=eval_metrics,
        )

        readme_path = checkpoint_dir / "README.md"
        readme_path.write_text(model_card_content, encoding="utf-8")

        # Upload folder
        upload_info = api.upload_folder(
            folder_path=str(checkpoint_dir),
            repo_id=repo_id,
            token=hf_token,
            repo_type="model",
            commit_message="Upload fine-tuned Bangla LoRA adapter and tokenizer",
        )

        repo_url = f"https://huggingface.co/{repo_id}"
        logger.info(f"Successfully uploaded model to Hugging Face Hub: {repo_url}")

        return {
            "status": "success",
            "repo_id": repo_id,
            "repo_url": repo_url,
            "commit_id": str(upload_info),
        }

    @classmethod
    def _generate_model_card(
        cls,
        repo_id: str,
        base_model_name: str,
        tasks: List[str],
        eval_metrics: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Construct comprehensive Hugging Face YAML model card metadata."""
        tasks_list_str = "\n".join([f"- `{t}`" for t in tasks])

        eval_section = ""
        if eval_metrics and "tasks" in eval_metrics:
            eval_section = "### 📊 Benchmark Evaluation\n\n"
            t_data = eval_metrics["tasks"]
            if "article_categorization" in t_data:
                eval_section += f"- **Categorization Accuracy**: `{t_data['article_categorization'].get('accuracy', 0.0) * 100:.1f}%`\n"
            if "headline_generation" in t_data:
                eval_section += f"- **Headline Generation ROUGE-L**: `{t_data['headline_generation'].get('rougeL', 0.0):.4f}`\n"
            if "content_summarization" in t_data:
                eval_section += f"- **Summarization ROUGE-1**: `{t_data['content_summarization'].get('rouge1', 0.0):.4f}`\n"
            if "named_entity_recognition" in t_data:
                eval_section += f"- **Named Entity Recognition (NER) F1**: `{t_data['named_entity_recognition'].get('f1', 0.0):.4f}`\n"

        return f"""---
language:
- bn
- en
tags:
- peft
- lora
- causal-lm
- bangla-nlp
- news-summarization
- text-classification
- ner
base_model: {base_model_name}
pipeline_tag: text-generation
license: apache-2.0
---

# {repo_id}

This repository contains a **lightweight LoRA adapter** fine-tuned on Bangla domain news articles for multi-task processing.

## 🎯 Supported Specialized Tasks
{tasks_list_str}

{eval_section}

## 🚀 Quick Start & Inference in Python

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
import torch

base_model_name = "{base_model_name}"
adapter_name = "{repo_id}"

# 1. Load Tokenizer and Base Model
tokenizer = AutoTokenizer.from_pretrained(adapter_name)
base_model = AutoModelForCausalLM.from_pretrained(base_model_name)

# 2. Attach LoRA Adapter
model = PeftModel.from_pretrained(base_model, adapter_name)
model.eval()

# 3. Generate Prediction
prompt = "[টাস্ক: সারসংক্ষেপ তৈরি]\\nখবর: আপনার বাংলা সংবাদ পাঠ্য এখানে দিন...\\n-> সারসংক্ষেপ:"
inputs = tokenizer(prompt, return_tensors="pt")

with torch.no_grad():
    outputs = model.generate(**inputs, max_new_tokens=100, do_sample=False)

print(tokenizer.decode(outputs[0], skip_special_tokens=True))
```

## 🛠️ Training Specifications
- **Base Model**: `{base_model_name}`
- **LoRA Rank ($r$)**: `8`
- **LoRA Alpha ($\alpha$)**: `16`
- **Target Modules**: Attention projections (`q_proj, v_proj` or `c_attn`)
- **Framework**: PyTorch + Hugging Face PEFT (CPU/GPU)

---
*Created automatically with WebCreoling AI Pipeline.*
"""
