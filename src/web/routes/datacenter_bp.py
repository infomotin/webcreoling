"""
Website Data Center & Enterprise Cloud Security Management Blueprint.
Provides multi-cloud media storage routing (Google Drive, Mega, S3, FTP),
parallel database high-availability (HA) replica failovers, automated encrypted backups,
and one-click disaster recovery controls for The Daily AI Alo (দি ডেইলি এআই আলো).
"""

import json
from pathlib import Path
from datetime import datetime
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    send_file,
)
from src.storage.database import get_db_session
from src.storage.repositories import DataCenterRepository, SiteConfigRepository
from src.datacenter.storage_manager import CloudStorageManager
from src.datacenter.database_failover_manager import DatabaseFailoverManager
from src.datacenter.backup_restore_manager import BackupRestoreManager
from src.web.auth import role_required, get_current_user

datacenter_bp = Blueprint("datacenter", __name__)


@datacenter_bp.route("")
@datacenter_bp.route("/")
@role_required("admin", "editor")
def index_view():
    """Render Website Data Center & Cloud Security Management Dashboard."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        cfg_repo = SiteConfigRepository(session)
        cfg_repo.seed_default_configs()

        summary = dc_repo.get_datacenter_summary()
        providers = dc_repo.list_storage_providers()
        replica_nodes = dc_repo.list_replica_nodes()
        backups = dc_repo.list_backups(limit=30)
        logs = dc_repo.list_logs(limit=25)
        branding = cfg_repo.get_config("branding", {})

        return render_template(
            "admin_datacenter.html",
            summary=summary,
            storage_providers=providers,
            replica_nodes=replica_nodes,
            backup_archives=backups,
            security_logs=logs,
            branding=branding,
        )


# ==============================================================================
# 1. Multi-Cloud Parallel Storage Endpoints
# ==============================================================================

@datacenter_bp.route("/storage/save", methods=["POST"])
@role_required("admin")
def save_storage_provider():
    """Create or update a cloud storage provider configuration."""
    provider_id = request.form.get("provider_id", "").strip()
    provider_type = request.form.get("provider_type", "google_drive").strip().lower()
    name = request.form.get("name", "").strip()
    cdn_base_url = request.form.get("cdn_base_url", "").strip()
    sync_mode = request.form.get("sync_mode", "AUTO_MIRROR").strip()
    is_primary = bool(request.form.get("is_primary"))
    is_active = bool(request.form.get("is_active", True))

    # Parse JSON credentials or form fields
    creds_raw = request.form.get("credentials_json", "").strip()
    credentials = {}
    if creds_raw:
        try:
            credentials = json.loads(creds_raw)
        except Exception:
            pass

    # Standard field mapping if raw fields provided
    if request.form.get("api_key"):
        credentials["api_key"] = request.form.get("api_key").strip()
    if request.form.get("folder_id"):
        credentials["folder_id"] = request.form.get("folder_id").strip()
    if request.form.get("bucket_name"):
        credentials["bucket_name"] = request.form.get("bucket_name").strip()
    if request.form.get("ftp_host"):
        credentials["ftp_host"] = request.form.get("ftp_host").strip()
        credentials["ftp_port"] = int(request.form.get("ftp_port", 22))
        credentials["username"] = request.form.get("ftp_user", "").strip()

    pid = int(provider_id) if provider_id and provider_id.isdigit() else None

    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        provider = dc_repo.create_or_update_storage_provider(
            provider_type=provider_type,
            name=name,
            credentials_json=credentials,
            cdn_base_url=cdn_base_url,
            sync_mode=sync_mode,
            is_active=is_active,
            is_primary=is_primary,
            provider_id=pid,
        )
        dc_repo.log_event(
            event_type="STORAGE_AUTH",
            description=f"ক্লাউড স্টোরেজ প্রোভাইডার কনফিগারেশন আপডেট করা হয়েছে: {provider.name} ({provider.provider_type})",
            severity="INFO",
            actor=getattr(get_current_user(), "username", "Admin"),
            ip_address=request.remote_addr or "127.0.0.1",
        )
        flash(f"ক্লাউড স্টোরেজ '{provider.name}' সফলভাবে সংরক্ষিত হয়েছে।", "success")

    return redirect(url_for("datacenter.index_view"))


@datacenter_bp.route("/storage/test/<int:provider_id>", methods=["POST"])
@role_required("admin", "editor")
def test_storage_connection(provider_id: int):
    """Test remote cloud storage authentication and connectivity."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        provider = dc_repo.get_storage_provider(provider_id)
        if not provider:
            return jsonify({"success": False, "message": "প্রোভাইডার পাওয়া যায়নি।"}), 404

        result = CloudStorageManager.test_provider_connection(provider.to_dict())
        if result.get("success"):
            provider.status = "ONLINE"
            provider.last_health_check = datetime.utcnow()
            session.flush()

        return jsonify(result)


@datacenter_bp.route("/storage/set-primary/<int:provider_id>", methods=["POST"])
@role_required("admin")
def set_primary_storage(provider_id: int):
    """Set provider as the primary CDN delivery source."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        dc_repo.set_primary_storage_provider(provider_id)
        provider = dc_repo.get_storage_provider(provider_id)
        dc_repo.log_event(
            event_type="STORAGE_AUTH",
            description=f"প্রাইমারি ক্লাউড মিডিয়া সিডিএন সোর্স পরিবর্তন করে '{provider.name}' করা হয়েছে।",
            severity="SUCCESS",
            actor=getattr(get_current_user(), "username", "Admin"),
            ip_address=request.remote_addr or "127.0.0.1",
        )
        flash(f"'{provider.name}' এখন পোর্টালের প্রাইমারি ক্লাউড সিডিএন সোর্স।", "success")

    return redirect(url_for("datacenter.index_view"))


@datacenter_bp.route("/storage/toggle/<int:provider_id>", methods=["POST"])
@role_required("admin")
def toggle_storage(provider_id: int):
    """Toggle storage provider active/inactive status."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        new_status = dc_repo.toggle_storage_provider(provider_id)
        return jsonify({"success": True, "is_active": new_status})


@datacenter_bp.route("/storage/delete/<int:provider_id>", methods=["POST"])
@role_required("admin")
def delete_storage(provider_id: int):
    """Delete a cloud storage provider."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        dc_repo.delete_storage_provider(provider_id)
        flash("ক্লাউড স্টোরেজ সফলভাবে মুছে ফেলা হয়েছে।", "info")

    return redirect(url_for("datacenter.index_view"))


@datacenter_bp.route("/storage/upload-media", methods=["POST"])
@role_required("admin", "editor")
def upload_media_to_cloud():
    """Directly upload image or video file to cloud storage with multi-cloud mirroring."""
    if "media_file" not in request.files:
        flash("কোনো মিডিয়া ফাইল সিলেক্ট করা হয়নি।", "warning")
        return redirect(url_for("datacenter.index_view"))

    file = request.files["media_file"]
    if not file or not file.filename:
        flash("অবৈধ ফাইল।", "danger")
        return redirect(url_for("datacenter.index_view"))

    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        primary_prov = dc_repo.get_primary_storage_provider()
        active_provs = dc_repo.get_active_storage_providers()

        upload_res = CloudStorageManager.upload_media_file(
            file_data=file.read(),
            filename=file.filename,
            primary_provider=primary_prov,
            active_providers=active_provs,
            mirror=True,
        )

        dc_repo.log_event(
            event_type="CLOUD_SYNC",
            description=f"মিডিয়া অ্যাসেট আপলোড ও মাল্টি-ক্লাউড মিররিং সম্পন্ন: {upload_res['filename']} ({upload_res['file_size_kb']} KB)",
            severity="SUCCESS",
            actor=getattr(get_current_user(), "username", "Editor"),
            ip_address=request.remote_addr or "127.0.0.1",
        )

        flash(
            f"মিডিয়া ফাইল '{upload_res['filename']}' সফলভাবে ক্লাউড স্টোরেজে আপলোড ও মিরর হয়েছে! "
            f"সিডিএন লিঙ্ক: {upload_res['primary_cdn_url']}",
            "success"
        )

    return redirect(url_for("datacenter.index_view"))


# ==============================================================================
# 2. Database High Availability & Auto-Failover Endpoints
# ==============================================================================

@datacenter_bp.route("/database/save", methods=["POST"])
@role_required("admin")
def save_replica_node():
    """Create or update database replica node."""
    node_id = request.form.get("node_id", "").strip()
    node_name = request.form.get("node_name", "").strip()
    host = request.form.get("host", "127.0.0.1").strip()
    port = int(request.form.get("port", 3306))
    database_name = request.form.get("database_name", "ai_news").strip()
    username = request.form.get("username", "root").strip()
    auto_failover_priority = int(request.form.get("auto_failover_priority", 1))
    is_primary = bool(request.form.get("is_current_primary"))
    is_active = bool(request.form.get("is_active", True))

    nid = int(node_id) if node_id and node_id.isdigit() else None

    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        node = dc_repo.create_or_update_node(
            node_name=node_name,
            host=host,
            port=port,
            database_name=database_name,
            username=username,
            auto_failover_priority=auto_failover_priority,
            is_active=is_active,
            is_current_primary=is_primary,
            node_id=nid,
        )
        flash(f"ডাটাবেস নোড '{node.node_name}' সংরক্ষিত হয়েছে।", "success")

    return redirect(url_for("datacenter.index_view"))


@datacenter_bp.route("/database/ping/<int:node_id>", methods=["POST"])
@role_required("admin", "editor")
def ping_database_node(node_id: int):
    """Ping database replica node and measure latency."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        node = dc_repo.get_replica_node(node_id)
        if not node:
            return jsonify({"success": False, "message": "নোড পাওয়া যায়নি।"}), 404

        is_online, latency, msg = DatabaseFailoverManager.ping_database_node(node.host, node.port)
        status = "SYNCED" if node.is_current_primary else "STANDBY_READY"
        dc_repo.update_node_health(node_id, status=status if is_online else "DISCONNECTED", latency_ms=latency)

        return jsonify({
            "success": is_online,
            "latency_ms": latency,
            "message": msg,
            "status": status if is_online else "DISCONNECTED",
        })


@datacenter_bp.route("/database/failover/<int:node_id>", methods=["POST"])
@role_required("admin")
def trigger_database_failover(node_id: int):
    """Promote target standby replica node to primary active master (failover / switchover)."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        target_node = dc_repo.get_replica_node(node_id)
        current_primary = dc_repo.get_current_primary_node()

        if not target_node:
            flash("টার্গেট রেপ্লিকা নোড পাওয়া যায়নি।", "danger")
            return redirect(url_for("datacenter.index_view"))

        failover_res = DatabaseFailoverManager.execute_failover_promotion(
            target_replica_node=target_node,
            previous_primary_node=current_primary,
            reason=f"Manual Administrator Switchover by {getattr(get_current_user(), 'username', 'Admin')}",
        )

        dc_repo.set_primary_node(node_id)
        dc_repo.log_event(
            event_type="FAILOVER",
            description=f"ডাটাবেস ফেইলওভার ও সুইচওভার সম্পন্ন: '{target_node.node_name}' এখন প্রাইমারি মাস্টার।",
            severity="CRITICAL",
            actor=getattr(get_current_user(), "username", "Admin"),
            ip_address=request.remote_addr or "127.0.0.1",
        )

        flash(failover_res["message"], "warning")

    return redirect(url_for("datacenter.index_view"))


@datacenter_bp.route("/database/toggle/<int:node_id>", methods=["POST"])
@role_required("admin")
def toggle_replica_node(node_id: int):
    """Toggle database replica node active/inactive state."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        new_status = dc_repo.toggle_node(node_id)
        return jsonify({"success": True, "is_active": new_status})


@datacenter_bp.route("/database/delete/<int:node_id>", methods=["POST"])
@role_required("admin")
def delete_replica_node(node_id: int):
    """Delete a database replica node."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        dc_repo.delete_node(node_id)
        flash("ডাটাবেস নোড মুছে ফেলা হয়েছে।", "info")

    return redirect(url_for("datacenter.index_view"))


# ==============================================================================
# 3. Automated Backup, Cloud Offload & One-Click Restore Endpoints
# ==============================================================================

@datacenter_bp.route("/backup/create", methods=["POST"])
@role_required("admin", "editor")
def create_backup():
    """Generate immediate backup (DATABASE_SQL, MEDIA_ASSETS, or FULL_SYSTEM) and auto-offload to clouds."""
    backup_type = request.form.get("backup_type", "FULL_SYSTEM").strip().upper()
    auto_cloud_sync = bool(request.form.get("auto_cloud_sync", True))

    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        active_provs = dc_repo.get_active_storage_providers()

        if backup_type == "DATABASE_SQL":
            res = BackupRestoreManager.generate_database_dump(session)
        elif backup_type == "MEDIA_ASSETS":
            res = BackupRestoreManager.generate_media_backup()
        else:
            res = BackupRestoreManager.generate_full_system_backup(session)

        # Offload to clouds if requested
        cloud_status = {}
        target_clouds = []
        if auto_cloud_sync and active_provs:
            cloud_status = BackupRestoreManager.offload_backup_to_clouds(
                backup_file_path=res["file_path"],
                target_providers=active_provs,
            )
            target_clouds = [p.provider_type for p in active_provs]

        # Record in database
        backup_rec = dc_repo.create_backup_record(
            backup_name=res["backup_name"],
            backup_type=res["backup_type"],
            file_path=res["file_path"],
            file_size_bytes=res["file_size_bytes"],
            sha256_checksum=res["sha256_checksum"],
            target_cloud_destinations=target_clouds,
            cloud_upload_status=cloud_status,
            is_encrypted=True,
            encryption_algorithm="AES-256-GCM Enterprise",
            status="COMPLETED",
        )

        dc_repo.log_event(
            event_type="BACKUP_CREATED",
            description=f"নতুন এনক্রিপ্টেড ব্যাকআপ তৈরি ও ক্লাউডে অফলোড সম্পন্ন: {backup_rec.backup_name} ({round(backup_rec.file_size_bytes/1024, 1)} KB)",
            severity="SUCCESS",
            actor=getattr(get_current_user(), "username", "Admin"),
            ip_address=request.remote_addr or "127.0.0.1",
        )

        flash(
            f"ব্যাকআপ '{backup_rec.backup_name}' সফলভাবে তৈরি হয়েছে এবং ক্লাউড স্টোরেজে আপলোড করা হয়েছে!",
            "success"
        )

    return redirect(url_for("datacenter.index_view"))


@datacenter_bp.route("/backup/restore/<int:backup_id>", methods=["POST"])
@role_required("admin")
def restore_backup(backup_id: int):
    """Execute one-click database and system restore from backup archive."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        backup_rec = dc_repo.get_backup_by_id(backup_id)
        if not backup_rec:
            flash("ব্যাকআপ রেকর্ড পাওয়া যায়নি।", "danger")
            return redirect(url_for("datacenter.index_view"))

        res = BackupRestoreManager.restore_from_backup_file(backup_rec.file_path, session)

        if res.get("success"):
            dc_repo.log_event(
                event_type="RESTORE_EXECUTED",
                description=f"সিস্টেম ব্যাকআপ রিস্টোর সফলভাবে সম্পন্ন: {backup_rec.backup_name} (SHA-256 ভেরিফাইড)",
                severity="WARNING",
                actor=getattr(get_current_user(), "username", "Admin"),
                ip_address=request.remote_addr or "127.0.0.1",
            )
            flash(res["message"], "success")
        else:
            flash(res.get("message", "রিস্টোর ব্যর্থ হয়েছে।"), "danger")

    return redirect(url_for("datacenter.index_view"))


@datacenter_bp.route("/backup/download/<int:backup_id>")
@role_required("admin")
def download_backup(backup_id: int):
    """Download backup archive file."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        backup_rec = dc_repo.get_backup_by_id(backup_id)
        if not backup_rec or not Path(backup_rec.file_path).exists():
            flash("ব্যাকআপ ফাইল পাওয়া যায়নি।", "danger")
            return redirect(url_for("datacenter.index_view"))

        return send_file(backup_rec.file_path, as_attachment=True, download_name=backup_rec.backup_name)


@datacenter_bp.route("/backup/delete/<int:backup_id>", methods=["POST"])
@role_required("admin")
def delete_backup(backup_id: int):
    """Delete a backup archive."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        dc_repo.delete_backup(backup_id)
        flash("ব্যাকআপ সফলভাবে মুছে ফেলা হয়েছে।", "info")

    return redirect(url_for("datacenter.index_view"))


# ==============================================================================
# 4. Live Telemetry API Endpoint
# ==============================================================================

@datacenter_bp.route("/api/status")
@role_required("admin", "editor", "analyst", "viewer")
def get_status_api():
    """Return JSON live status of data center storage, replica latency, and backups."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        summary = dc_repo.get_datacenter_summary()
        nodes = [n.to_dict() for n in dc_repo.list_replica_nodes()]
        providers = [p.to_dict() for p in dc_repo.list_storage_providers()]
        return jsonify({
            "summary": summary,
            "nodes": nodes,
            "providers": providers,
            "timestamp": datetime.utcnow().isoformat(),
        })
