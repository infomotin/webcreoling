"""
Multi-Task Model Evaluator.
Computes task-specific metrics across Categorization, Headline Gen, Summarization, and NER.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import evaluate
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from peft import PeftModel
from config.settings import settings
from src.common.logger import get_logger
from src.common.utils import safe_write_json
from src.finetuning.tasks import TaskPrefixes, SpecializedTaskManager

logger = get_logger("webcreoling.finetuning.evaluator")


class MultiTaskEvaluator:
    """Evaluates fine-tuned hybrid model across all 4 news skills."""

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        base_model_name: str = settings.BASE_MODEL_NAME,
    ):
        self.model_dir = model_dir or (settings.CHECKPOINTS_DIR / "final_specialized_model")
        self.base_model_name = base_model_name
        self.rouge_metric = evaluate.load("rouge")
        self.bleu_metric = evaluate.load("bleu")
        self.model, self.tokenizer = self._load_model_and_tokenizer()

    def _load_model_and_tokenizer(self) -> Tuple[Any, Any]:
        """Load fine-tuned PeftModel or base model."""
        try:
            tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        except Exception:
            tokenizer = AutoTokenizer.from_pretrained(self.base_model_name)

        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token or "<|endoftext|>"
            tokenizer.pad_token_id = tokenizer.eos_token_id

        try:
            # Check if LoRA adapter is in model_dir
            if (self.model_dir / "adapter_config.json").exists():
                base_model = AutoModelForCausalLM.from_pretrained(self.base_model_name)
                base_model.resize_token_embeddings(len(tokenizer))
                model = PeftModel.from_pretrained(base_model, str(self.model_dir))
                logger.info(f"Loaded PeftModel adapter from {self.model_dir}")
            else:
                model = AutoModelForCausalLM.from_pretrained(str(self.model_dir))
                logger.info(f"Loaded standalone model from {self.model_dir}")
        except Exception as e:
            logger.warning(f"Failed to load fine-tuned model from {self.model_dir}: {e}. Loading base.")
            model = AutoModelForCausalLM.from_pretrained(self.base_model_name)
            model.resize_token_embeddings(len(tokenizer))

        model.eval()
        return model, tokenizer

    def generate_response(self, prompt: str, max_new_tokens: int = 80) -> str:
        """Generate text completion given a prompt."""
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        decoded = self.tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return decoded.strip()

    def evaluate_categorization(self, test_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Evaluate article categorization accuracy."""
        correct = 0
        total = 0
        for sample in test_samples:
            content = sample.get("content", "")
            target_cat = (sample.get("category") or "general").strip().lower()
            prompt = f"{TaskPrefixes.CATEGORIZE}\nখবর: {content[:400]}\n-> বিভাগ:"
            pred = self.generate_response(prompt, max_new_tokens=15).strip().lower()
            if target_cat in pred or pred in target_cat:
                correct += 1
            total += 1

        accuracy = correct / max(total, 1)
        return {"accuracy": round(accuracy, 4), "total_evaluated": total, "correct": correct}

    def evaluate_headline_generation(self, test_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Evaluate headline generation using ROUGE and BLEU metrics."""
        predictions = []
        references = []
        for sample in test_samples:
            content = sample.get("content", "")
            title = sample.get("title", "")
            if not title or not content:
                continue
            prompt = f"{TaskPrefixes.HEADLINE}\nখবর: {content[:500]}\n-> শিরোনাম:"
            pred = self.generate_response(prompt, max_new_tokens=30).split("\n")[0].strip()
            predictions.append(pred or "সংবাদ")
            references.append(title)

        if not predictions:
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0, "bleu": 0.0}

        rouge_scores = self.rouge_metric.compute(predictions=predictions, references=references)
        bleu_scores = self.bleu_metric.compute(predictions=predictions, references=[[r] for r in references])

        return {
            "rouge1": round(rouge_scores.get("rouge1", 0.0), 4),
            "rouge2": round(rouge_scores.get("rouge2", 0.0), 4),
            "rougeL": round(rouge_scores.get("rougeL", 0.0), 4),
            "bleu": round(bleu_scores.get("bleu", 0.0), 4),
            "samples_evaluated": len(predictions),
        }

    def evaluate_summarization(self, test_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Evaluate article summarization using ROUGE scores."""
        predictions = []
        references = []
        for sample in test_samples:
            content = sample.get("content", "")
            summary = sample.get("summary") or content[:120]
            prompt = f"{TaskPrefixes.SUMMARIZE}\nখবর: {content[:600]}\n-> সারসংক্ষেপ:"
            pred = self.generate_response(prompt, max_new_tokens=60).split("\n")[0].strip()
            predictions.append(pred or "সারসংক্ষেপ")
            references.append(summary)

        if not predictions:
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}

        rouge_scores = self.rouge_metric.compute(predictions=predictions, references=references)
        return {
            "rouge1": round(rouge_scores.get("rouge1", 0.0), 4),
            "rouge2": round(rouge_scores.get("rouge2", 0.0), 4),
            "rougeL": round(rouge_scores.get("rougeL", 0.0), 4),
            "samples_evaluated": len(predictions),
        }

    def evaluate_ner(self, test_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Evaluate Named Entity Recognition precision, recall, and F1."""
        true_positives = 0
        false_positives = 0
        false_negatives = 0

        for sample in test_samples:
            content = sample.get("content", "")
            expected_entities = sample.get("entities") or SpecializedTaskManager.heuristic_extract_entities(content)
            expected_flat = set(
                [e for sub in expected_entities.values() for e in (sub if isinstance(sub, list) else [sub])]
            )

            prompt = f"{TaskPrefixes.NER}\nখবর: {content[:400]}\n-> সত্তা:"
            pred_text = self.generate_response(prompt, max_new_tokens=50)

            # Extract any matched entity tokens from prediction text
            predicted_flat = set([e for e in expected_flat if e in pred_text])

            tp = len(predicted_flat.intersection(expected_flat))
            fp = max(0, len(predicted_flat) - tp)
            fn = len(expected_flat - predicted_flat)

            true_positives += tp
            false_positives += fp
            false_negatives += fn

        precision = true_positives / max(true_positives + false_positives, 1)
        recall = true_positives / max(true_positives + false_negatives, 1)
        f1 = (2 * precision * recall) / max(precision + recall, 1e-6)

        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "samples_evaluated": len(test_samples),
        }

    def run_full_evaluation(self, test_samples: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Execute comprehensive evaluation across all 4 tasks and save report."""
        if not test_samples:
            from src.scraper.mock_bangla_portal import MOCK_ARTICLES
            test_samples = MOCK_ARTICLES

        logger.info("Running evaluation across all 4 specialized skills...")
        cat_metrics = self.evaluate_categorization(test_samples)
        headline_metrics = self.evaluate_headline_generation(test_samples)
        summary_metrics = self.evaluate_summarization(test_samples)
        ner_metrics = self.evaluate_ner(test_samples)

        report = {
            "model_path": str(self.model_dir),
            "tasks": {
                "article_categorization": cat_metrics,
                "headline_generation": headline_metrics,
                "content_summarization": summary_metrics,
                "named_entity_recognition": ner_metrics,
            },
        }

        report_path = self.model_dir / "evaluation_report.json"
        safe_write_json(report_path, report)
        logger.info(f"Full evaluation report saved to {report_path}")
        return report
