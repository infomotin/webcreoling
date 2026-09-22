"""
LLM Training & LoRA Fine-Tuning Blueprint.
Provides interactive controls, theoretical visualizers, learning roadmap, and training endpoints.
"""

from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from config.settings import settings
from src.common.utils import safe_read_json
from src.training.base_trainer import BaseLLMTrainer
from src.finetuning.hybrid_trainer import HybridFineTuner
from src.finetuning.evaluator import MultiTaskEvaluator
from src.web.auth import login_required, roles_required

training_bp = Blueprint("training", __name__)


@training_bp.route("")
@login_required
def index_view():
    """Display model checkpoint status, parameters, interactive visualizers, and learning framework."""
    base_checkpoint_dir = settings.CHECKPOINTS_DIR / "base_model"
    specialized_dir = settings.CHECKPOINTS_DIR / "final_specialized_model"
    eval_report_file = specialized_dir / "evaluation_report.json"
    manifest_file = specialized_dir / "llama_cpp_manifest.json"

    base_exists = (base_checkpoint_dir / "model.safetensors").exists() or (base_checkpoint_dir / "pytorch_model.bin").exists() or (base_checkpoint_dir / "config.json").exists()
    specialized_exists = (specialized_dir / "adapter_config.json").exists() or (specialized_dir / "config.json").exists()

    eval_report = safe_read_json(eval_report_file) if eval_report_file.exists() else None
    manifest = safe_read_json(manifest_file) if manifest_file.exists() else None

    return render_template(
        "training.html",
        settings=settings,
        base_exists=base_exists,
        specialized_exists=specialized_exists,
        eval_report=eval_report,
        manifest=manifest,
    )


@training_bp.route("/api/metrics")
@login_required
def get_training_metrics():
    """Return simulated or actual historical loss curves and checkpoint metrics for dynamic rendering."""
    specialized_dir = settings.CHECKPOINTS_DIR / "final_specialized_model"
    eval_report_file = specialized_dir / "evaluation_report.json"
    eval_report = safe_read_json(eval_report_file) if eval_report_file.exists() else {}

    # Sample epoch loss curve for visualization
    loss_history = {
        "epochs": [1, 2, 3, 4, 5],
        "train_loss": [3.42, 2.51, 1.94, 1.76, 1.62],
        "eval_loss": [3.55, 2.68, 2.05, 1.82, 1.69],
        "perplexity": [34.8, 14.5, 7.7, 6.1, 5.4],
    }

    return jsonify({
        "status": "success",
        "loss_history": loss_history,
        "eval_report": eval_report,
    })


@training_bp.route("/api/format-sft", methods=["POST"])
@login_required
def format_sft_sample():
    """Format and validate an SFT reasoning sample with token masking preview."""
    data = request.get_json() or {}
    instruction = data.get("instruction", "").strip()
    reasoning = data.get("reasoning", "").strip()
    response = data.get("response", "").strip()
    system_prompt = data.get("system_prompt", "You are an expert Bangla AI language model.")

    if not instruction:
        return jsonify({"error": "Instruction cannot be empty"}), 400

    formatted_text = (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{instruction}<|im_end|>\n"
        f"<|im_start|>thought\n{reasoning}<|im_end|>\n"
        f"<|im_start|>assistant\n{response}<|im_end|>"
    )

    token_estimate = len(formatted_text.split()) * 1.3

    return jsonify({
        "status": "success",
        "formatted_text": formatted_text,
        "token_estimate": int(token_estimate),
        "jsonl_record": {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": instruction},
                {"role": "thought", "content": reasoning},
                {"role": "assistant", "content": response},
            ]
        }
    })


@training_bp.route("/train-base", methods=["POST"])
@roles_required("admin")
def train_base_model():
    """Trigger CPU base causal language model pre-training."""
    epochs = int(request.form.get("epochs", 1))
    trainer = BaseLLMTrainer()
    try:
        summary = trainer.train(num_epochs=epochs, batch_size=settings.TRAIN_BATCH_SIZE)
        flash(f"Base Causal LM trained successfully! (Validation Loss: {summary['eval_loss']:.4f})", "success")
    except Exception as e:
        flash(f"Error during base model training: {e}", "danger")

    return redirect(url_for("training.index_view"))


@training_bp.route("/finetune", methods=["POST"])
@roles_required("admin")
def finetune_lora():
    """Trigger multi-task LoRA fine-tuning across all 4 skills."""
    epochs = int(request.form.get("epochs", 2))
    tuner = HybridFineTuner()
    try:
        summary = tuner.fine_tune(num_epochs=epochs, batch_size=settings.TRAIN_BATCH_SIZE)
        # Run evaluation
        evaluator = MultiTaskEvaluator()
        evaluator.run_full_evaluation()
        flash(f"Hybrid LoRA fine-tuning completed across 4 tasks! (Loss: {summary['eval_loss']:.4f})", "success")
    except Exception as e:
        flash(f"Error during LoRA fine-tuning: {e}", "danger")

    return redirect(url_for("training.index_view"))

