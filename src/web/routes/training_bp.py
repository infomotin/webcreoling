"""
LLM Training & LoRA Fine-Tuning Blueprint.
Allows Admins to trigger CPU model training, view checkpoints, and inspect evaluation reports.
"""

from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash
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
    """Display model checkpoint status, parameters, and evaluation metrics."""
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
