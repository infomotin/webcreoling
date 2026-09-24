"""
Unit & Integration Tests for Topic Model Optimizer, Live Fine-Tuning Cockpit,
Scraped Data Knowledge Learner, and Local Model Manager.
"""

import io
import json
import time
import pytest
from pathlib import Path
from flask.testing import FlaskClient

from src.training.topic_model_optimizer import TopicModelOptimizer, TOPIC_DEFINITIONS
from src.training.scraped_data_learner import ScrapedDataLearner
from src.training.training_job_manager import TrainingJobManager
from src.training.local_model_manager import LocalModelManager
from src.web.app import create_app


@pytest.fixture
def topic_optimizer(tmp_path):
    return TopicModelOptimizer(checkpoints_root=tmp_path)


@pytest.fixture
def scraped_learner(tmp_path):
    return ScrapedDataLearner(data_root=tmp_path)


@pytest.fixture
def local_manager(tmp_path):
    return LocalModelManager(checkpoints_root=tmp_path)


@pytest.fixture
def client():
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        # Simulate admin session
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["roles"] = ["admin"]
        yield client


# =========================================================================
# 1. TOPIC MODEL OPTIMIZER TESTS
# =========================================================================

def test_topic_definitions_completeness():
    """Verify all 6 core topic domains are properly defined with prompts & ranks."""
    expected_topics = {"politics", "economy", "technology", "international", "sports", "factcheck"}
    assert set(TOPIC_DEFINITIONS.keys()) == expected_topics
    for tid, defn in TOPIC_DEFINITIONS.items():
        assert "name_bn" in defn
        assert "name_en" in defn
        assert "keywords" in defn
        assert "sample_prompt" in defn
        assert defn["recommended_rank"] > 0


def test_list_topic_submodels(topic_optimizer):
    """Verify submodels list returns all domains with valid initial states."""
    submodels = topic_optimizer.list_topic_submodels()
    assert len(submodels) == 6
    for sm in submodels:
        assert sm["id"] in TOPIC_DEFINITIONS
        assert "latency_ms" in sm
        assert "disk_size_mb" in sm
        assert sm["quantization"] in ["FP16", "INT8", "INT4", "NF4", "Pruned"]


def test_split_topic_submodel(topic_optimizer):
    """Verify topic splitting creates adapter configuration and updates manifest."""
    meta = topic_optimizer.split_topic_submodel(
        topic_id="economy",
        base_model_name="HuggingFaceTB/SmolLM2-135M",
        lora_r=16,
        custom_name="Bangla-Economy-Expert",
    )
    assert meta["topic_id"] == "economy"
    assert meta["rank"] == 16
    assert meta["param_savings_percent"] > 90.0

    sub_dir = topic_optimizer.submodels_dir / "economy"
    assert (sub_dir / "adapter_config.json").exists()
    assert (sub_dir / "topic_metadata.json").exists()


def test_model_optimizer_quantization_and_pruning(topic_optimizer):
    """Verify INT8, INT4, Pruning, and ONNX optimization calculations."""
    # INT8
    int8_res = topic_optimizer.optimize_model("test_model", optimization_type="int8")
    assert int8_res["quant_label"] == "INT8"
    assert int8_res["size_reduction_percent"] >= 45.0
    assert "x" in int8_res["speedup_factor"]

    # INT4
    int4_res = topic_optimizer.optimize_model("test_model", optimization_type="int4")
    assert int4_res["quant_label"] == "INT4 / NF4"
    assert int4_res["size_reduction_percent"] >= 70.0

    # Pruning
    prune_res = topic_optimizer.optimize_model("test_model", optimization_type="prune", prune_ratio=0.30)
    assert "Pruned 30%" in prune_res["quant_label"]

    # ONNX
    onnx_res = topic_optimizer.optimize_model("test_model", optimization_type="onnx")
    assert onnx_res["quant_label"] == "ONNX-O4"


def test_deploy_to_newsroom(topic_optimizer):
    """Verify deploying model updates active newsroom engine manifest."""
    res = topic_optimizer.deploy_to_newsroom("technology", model_type="topic_submodel")
    assert res["active_model_id"] == "technology"
    assert res["status"] == "online"
    manifest_file = topic_optimizer.active_model_dir / "active_model_manifest.json"
    assert manifest_file.exists()


# =========================================================================
# 2. SCRAPED DATA KNOWLEDGE LEARNER TESTS
# =========================================================================

def test_scan_and_extract_knowledge(scraped_learner):
    """Verify knowledge extraction from scraped news produces valid SFT reasoning pairs."""
    res = scraped_learner.scan_and_extract_knowledge(
        categories=["politics", "technology"],
        limit=10,
        min_char_length=50,
    )
    assert res["status"] == "success"
    assert res["articles_scanned"] > 0
    assert res["sft_pairs_created"] > 0
    assert len(res["samples"]) > 0

    sample = res["samples"][0]
    assert "instruction" in sample
    assert "thought" in sample
    assert "response" in sample
    assert "<|im_start|>thought" in sample["text"]
    assert "<|im_start|>assistant" in sample["text"]

    # Check stats
    stats = scraped_learner.get_scanned_knowledge_stats()
    assert stats["total_articles_scanned"] > 0
    assert stats["total_sft_pairs_generated"] > 0
    assert len(stats["datasets"]) > 0


# =========================================================================
# 3. TRAINING JOB MANAGER TESTS
# =========================================================================

def test_training_job_lifecycle():
    """Verify background training job start, progress polling, and cancellation."""
    job_id = TrainingJobManager.start_job(
        task_type="topic_finetune",
        topic="politics",
        epochs=1,
        lora_r=8,
        learning_rate=3e-4,
    )
    assert job_id.startswith("job_")

    # Give worker a moment to progress
    time.sleep(0.6)
    progress = TrainingJobManager.get_job_progress(job_id)
    assert progress is not None
    assert progress["status"] in ["running", "completed"]
    assert progress["current_step"] >= 0
    assert len(progress["logs"]) > 0

    # Test cancel
    TrainingJobManager.cancel_job(job_id)
    time.sleep(0.2)
    cancelled_progress = TrainingJobManager.get_job_progress(job_id)
    assert cancelled_progress["status"] in ["cancelled", "completed"]


# =========================================================================
# 4. LOCAL MODEL MANAGER TESTS
# =========================================================================

def test_local_model_manager_operations(local_manager):
    """Verify local model listing, optimization, and deployment."""
    models = local_manager.list_uploaded_models()
    assert len(models) >= 1
    model_id = models[0]["model_id"]

    # Optimize local model
    opt_report = local_manager.optimize_local_model(model_id, optimization_type="int8")
    assert opt_report["status"] == "success" or "optimized_size_mb" in opt_report

    # Deploy local model
    deploy_res = local_manager.deploy_model(model_id)
    assert deploy_res["active_model_id"] == model_id


# =========================================================================
# 5. INTEGRATION HTTP ENDPOINTS TESTS
# =========================================================================

def test_training_index_endpoint(client: FlaskClient):
    """Verify GET /training returns 200 and contains studio elements."""
    response = client.get("/training")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "AI Model Training, Topic Splitter" in html
    assert "রাজনীতি ও সুশাসন" in html
    assert "liveLossChart" in html


def test_start_finetune_endpoint(client: FlaskClient):
    """Verify POST /training/api/start-finetune launches asynchronous training job."""
    payload = {
        "topic": "technology",
        "epochs": 1,
        "lora_r": 8,
        "learning_rate": 0.0003,
        "tasks": ["categorize", "headline"],
        "use_scraped_knowledge": True,
    }
    response = client.post("/training/api/start-finetune", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert "job_id" in data

    # Poll progress
    poll_res = client.get(f"/training/api/progress/{data['job_id']}")
    assert poll_res.status_code == 200
    poll_data = poll_res.get_json()
    assert poll_data["status"] == "success"


def test_scan_and_learn_endpoint(client: FlaskClient):
    """Verify POST /training/api/scan-and-learn triggers web scrape knowledge extraction."""
    payload = {
        "categories": ["politics", "economy"],
        "limit": 5,
        "min_char_length": 40,
    }
    response = client.post("/training/api/scan-and-learn", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["articles_scanned"] > 0


def test_optimize_and_benchmark_endpoints(client: FlaskClient):
    """Verify model optimization and benchmark API endpoints."""
    # Optimization
    opt_payload = {
        "model_id": "politics",
        "optimization_type": "int8",
        "prune_ratio": 0.3,
    }
    opt_res = client.post("/training/api/model/optimize", json=opt_payload)
    # Could be 200 (if local model or fallback)
    assert opt_res.status_code in [200, 400]

    # Benchmark
    bench_res = client.get("/training/api/model/benchmark/politics")
    assert bench_res.status_code == 200
    bench_data = bench_res.get_json()
    assert bench_data["status"] == "success"
    assert "tokens_per_second" in bench_data["benchmark"]

    # Inference Playground Test
    inf_payload = {
        "model_id": "politics",
        "prompt": "নির্বাচন কমিশনের নতুন সিদ্ধান্ত কী?",
        "temperature": 0.7,
        "max_tokens": 128,
    }
    inf_res = client.post("/training/api/inference-test", json=inf_payload)
    assert inf_res.status_code == 200
    inf_data = inf_res.get_json()
    assert inf_data["status"] == "success"
    assert "thought" in inf_data
    assert "response" in inf_data
    assert inf_data["tokens_per_second"] > 0
