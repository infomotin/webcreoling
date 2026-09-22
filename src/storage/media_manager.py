"""
Media Manager for Local Image Storage & Deduplication.
Downloads, verifies, deduplicates using SHA-256, and organizes images in a structured directory layout.
"""

import io
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import httpx
from PIL import Image
from config.settings import settings
from src.common.logger import get_logger
from src.common.utils import compute_sha256, sanitize_filename

logger = get_logger("webcreoling.storage.media")


class MediaManager:
    """Manages local image downloading, SHA-256 deduplication, and filesystem organization."""

    def __init__(self, base_images_dir: Optional[Path] = None):
        self.base_dir = base_images_dir or settings.IMAGES_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {"User-Agent": settings.USER_AGENT}

    def get_target_path(
        self,
        source: str,
        file_hash: str,
        extension: str = "jpg",
        pub_date: Optional[datetime] = None,
    ) -> Path:
        """
        Compute organized filesystem path:
        data/images/<source>/<YYYY-MM>/<sha256_hash>.<ext>
        """
        source_clean = sanitize_filename(source.lower(), max_length=30)
        date_folder = (pub_date or datetime.utcnow()).strftime("%Y-%m")
        target_dir = self.base_dir / source_clean / date_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        ext = extension.lstrip(".").lower()
        if not ext or ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
            ext = "jpg"

        return target_dir / f"{file_hash[:16]}_{file_hash[-8:]}.{ext}"

    def download_and_store_image(
        self,
        image_url: str,
        source: str,
        pub_date: Optional[datetime] = None,
        timeout: int = 15,
    ) -> Optional[Dict[str, Any]]:
        """
        Download an image, compute SHA-256 hash, deduplicate, and store on disk.
        Returns a dictionary of metadata or None if download fails.
        """
        if not image_url or not image_url.startswith(("http://", "https://")):
            return None

        try:
            with httpx.Client(timeout=timeout, headers=self.headers, follow_redirects=True) as client:
                response = client.get(image_url)
                if response.status_code != 200:
                    logger.debug(f"Failed to download image from {image_url} (HTTP {response.status_code})")
                    return None

                data = response.content
                if not data or len(data) < 100:  # Skip trivial/empty responses
                    return None

                # Check max size limit
                max_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
                if len(data) > max_bytes:
                    logger.warning(f"Image from {image_url} exceeds max size limit ({len(data)} bytes). Skipping.")
                    return None

                # Validate image data with PIL and determine dimensions/format
                try:
                    img = Image.open(io.BytesIO(data))
                    width, height = img.size
                    img_format = (img.format or "JPEG").lower()
                    mime_type = f"image/{img_format}"
                except Exception as e:
                    logger.debug(f"Invalid image format from {image_url}: {e}")
                    return None

                # Compute SHA-256
                file_hash = compute_sha256(data)
                target_path = self.get_target_path(source, file_hash, extension=img_format, pub_date=pub_date)

                # Deduplication: only write if file doesn't already exist
                if not target_path.exists():
                    with open(target_path, "wb") as f:
                        f.write(data)
                    logger.debug(f"Saved new image to {target_path} ({len(data)} bytes)")
                else:
                    logger.debug(f"Image with hash {file_hash} already exists at {target_path} (deduplicated)")

                # Relative path from project root for database storage portability
                rel_path = str(target_path.relative_to(settings.BASE_DIR)).replace("\\", "/")

                return {
                    "original_url": image_url,
                    "local_path": rel_path,
                    "file_hash": file_hash,
                    "file_size_bytes": len(data),
                    "mime_type": mime_type,
                    "width": width,
                    "height": height,
                }

        except Exception as e:
            logger.debug(f"Error downloading image from {image_url}: {e}")
            return None
