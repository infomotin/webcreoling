"""
Cryptographic Blockchain-Style Immutable Ledger Engine for Article Verification.
Provides SHA-256 content hashing, Merkle root aggregation, HMAC-SHA256 digital signatures,
and chain audit validation to ensure 100% tamper-evident integrity.
"""

import hashlib
import hmac
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from config.settings import settings
from src.common.logger import get_logger

logger = get_logger("webcreoling.common.blockchain")

LEDGER_SECRET = getattr(settings, "SECRET_KEY", "prothom_alo_enterprise_cryptographic_ledger_secret_2026")
GENESIS_PREV_HASH = "0" * 64


class BlockchainLedgerEngine:
    """Cryptographic engine for hashing, signing, and auditing article blocks."""

    @staticmethod
    def sha256_text(text: str) -> str:
        """Calculate standard SHA-256 hex digest of UTF-8 string."""
        if text is None:
            text = ""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @classmethod
    def compute_merkle_root(cls, title_hash: str, content_hash: str, author_hash: str, ts_hash: str) -> str:
        """
        Compute a 4-leaf binary Merkle Tree root.
        Leaf 1: title_hash, Leaf 2: content_hash, Leaf 3: author_hash, Leaf 4: ts_hash
        """
        node_12 = hashlib.sha256((title_hash + content_hash).encode("utf-8")).hexdigest()
        node_34 = hashlib.sha256((author_hash + ts_hash).encode("utf-8")).hexdigest()
        root = hashlib.sha256((node_12 + node_34).encode("utf-8")).hexdigest()
        return root

    @classmethod
    def calculate_block_hash(
        cls,
        block_number: int,
        article_id: Optional[int],
        merkle_root: str,
        prev_block_hash: str,
        timestamp_iso: str,
        nonce: int = 0,
    ) -> str:
        """Compute SHA-256 block hash linking previous block and current Merkle root."""
        header = f"{block_number}|{article_id or 0}|{merkle_root}|{prev_block_hash}|{timestamp_iso}|{nonce}"
        return hashlib.sha256(header.encode("utf-8")).hexdigest()

    @classmethod
    def generate_digital_signature(cls, block_hash: str, secret_key: Optional[str] = None) -> str:
        """Generate HMAC-SHA256 digital signature certifying server ownership."""
        key = (secret_key or LEDGER_SECRET).encode("utf-8")
        sig = hmac.new(key, block_hash.encode("utf-8"), hashlib.sha256).hexdigest()
        return sig

    @classmethod
    def verify_digital_signature(cls, block_hash: str, signature: str, secret_key: Optional[str] = None) -> bool:
        """Verify HMAC-SHA256 signature authenticity."""
        expected = cls.generate_digital_signature(block_hash, secret_key)
        return hmac.compare_digest(expected, signature)

    @classmethod
    def create_genesis_block_data(cls) -> Dict[str, Any]:
        """Generate the Genesis Block (#0) anchor for the newspaper ledger."""
        ts = datetime(2026, 1, 1, 0, 0, 0)
        ts_iso = ts.isoformat()
        title_hash = cls.sha256_text("GENESIS_ROOT_PROTHOM_ALO_NEWSROOM_PORTAL")
        content_hash = cls.sha256_text("Enterprise immutable ledger initialized. All published articles are cryptographically sealed.")
        author_hash = cls.sha256_text("SYSTEM_ROOT_GENESIS")
        ts_hash = cls.sha256_text(ts_iso)
        merkle_root = cls.compute_merkle_root(title_hash, content_hash, author_hash, ts_hash)
        prev_hash = GENESIS_PREV_HASH
        block_hash = cls.calculate_block_hash(0, 0, merkle_root, prev_hash, ts_iso, 0)
        signature = cls.generate_digital_signature(block_hash)

        return {
            "block_number": 0,
            "article_id": None,
            "title_hash": title_hash,
            "content_hash": content_hash,
            "author_hash": author_hash,
            "merkle_root": merkle_root,
            "prev_block_hash": prev_hash,
            "block_hash": block_hash,
            "digital_signature": signature,
            "nonce": 0,
            "timestamp": ts,
            "verification_status": "VALID",
        }

    @classmethod
    def mint_article_block(
        cls,
        block_number: int,
        article_id: int,
        title: str,
        content_text: str,
        author: Optional[str],
        prev_block_hash: str,
        timestamp: Optional[datetime] = None,
        nonce: int = 0,
    ) -> Dict[str, Any]:
        """Mint a new verified cryptographic block for a published article."""
        ts = timestamp or datetime.utcnow()
        if isinstance(ts, datetime):
            ts = ts.replace(microsecond=0)
            ts_iso = ts.isoformat()
        else:
            ts_str = str(ts).strip().replace(" ", "T")
            if "." in ts_str:
                ts_str = ts_str.split(".")[0]
            ts_iso = ts_str

        title_hash = cls.sha256_text(title.strip())
        content_hash = cls.sha256_text(content_text.strip())
        author_hash = cls.sha256_text((author or "Editorial Staff").strip())
        ts_hash = cls.sha256_text(ts_iso)

        merkle_root = cls.compute_merkle_root(title_hash, content_hash, author_hash, ts_hash)
        block_hash = cls.calculate_block_hash(block_number, article_id, merkle_root, prev_block_hash, ts_iso, nonce)
        signature = cls.generate_digital_signature(block_hash)

        return {
            "block_number": block_number,
            "article_id": article_id,
            "title_hash": title_hash,
            "content_hash": content_hash,
            "author_hash": author_hash,
            "merkle_root": merkle_root,
            "prev_block_hash": prev_block_hash,
            "block_hash": block_hash,
            "digital_signature": signature,
            "nonce": nonce,
            "timestamp": ts,
            "verification_status": "VALID",
        }

    @classmethod
    def verify_article_block(
        cls,
        block: Dict[str, Any],
        title: str,
        content_text: str,
        author: Optional[str],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Verify an individual block's internal integrity against article content and signature.
        Returns: (is_valid, reason, details_dict)
        """
        raw_ts = block.get("timestamp")
        if isinstance(raw_ts, datetime):
            ts_iso = raw_ts.replace(microsecond=0).isoformat()
        elif raw_ts:
            ts_str = str(raw_ts).strip().replace(" ", "T")
            if "." in ts_str:
                ts_str = ts_str.split(".")[0]
            ts_iso = ts_str
        else:
            ts_iso = ""

        calc_title_hash = cls.sha256_text(title.strip())
        calc_content_hash = cls.sha256_text(content_text.strip())
        calc_author_hash = cls.sha256_text((author or "Editorial Staff").strip())
        ts_hash = cls.sha256_text(ts_iso)

        # Check content match
        if calc_title_hash != block.get("title_hash"):
            return False, "Title content has been tampered or modified from ledger state.", {"step": "title_hash_mismatch"}
        if calc_content_hash != block.get("content_hash"):
            return False, "Article body content has been altered from sealed ledger state.", {"step": "content_hash_mismatch"}

        # Check Merkle Root
        calc_merkle = cls.compute_merkle_root(calc_title_hash, calc_content_hash, calc_author_hash, ts_hash)
        if calc_merkle != block.get("merkle_root"):
            return False, "Merkle tree integrity violation.", {"step": "merkle_root_mismatch"}

        # Check Block Hash
        calc_block_hash = cls.calculate_block_hash(
            block["block_number"],
            block.get("article_id"),
            calc_merkle,
            block["prev_block_hash"],
            ts_iso,
            block.get("nonce", 0),
        )
        if calc_block_hash != block.get("block_hash"):
            return False, "Block hash mismatch. Block header altered.", {"step": "block_hash_mismatch"}

        # Check Digital Signature
        if not cls.verify_digital_signature(block["block_hash"], block.get("digital_signature", "")):
            return False, "Cryptographic server digital signature invalid or forged.", {"step": "signature_invalid"}

        return True, "Article cryptographic integrity 100% verified against immutable ledger.", {
            "block_number": block["block_number"],
            "block_hash": block["block_hash"],
            "merkle_root": block["merkle_root"],
            "prev_block_hash": block["prev_block_hash"],
            "digital_signature": block["digital_signature"],
            "status": "VALID",
        }

    @classmethod
    def audit_entire_chain(cls, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Comprehensive audit scanning all blocks in order to ensure no broken links or forged signatures.
        """
        if not blocks:
            return {
                "total_blocks": 0,
                "chain_valid": True,
                "status": "EMPTY",
                "message": "Ledger is empty. No blocks minted yet.",
                "tampered_blocks": [],
            }

        # Sort blocks by block_number ascending
        sorted_blocks = sorted(blocks, key=lambda b: b["block_number"])
        tampered = []
        prev_hash = GENESIS_PREV_HASH

        for idx, blk in enumerate(sorted_blocks):
            b_num = blk["block_number"]
            # Check sequential continuity
            if b_num != idx:
                tampered.append({
                    "block_number": b_num,
                    "reason": f"Non-sequential block index. Expected {idx}, found {b_num}.",
                })

            # Check previous hash link
            if idx > 0 and blk["prev_block_hash"] != prev_hash:
                tampered.append({
                    "block_number": b_num,
                    "reason": f"Broken chain link! Prev hash '{blk['prev_block_hash'][:12]}...' does not match block #{idx-1} hash '{prev_hash[:12]}...'.",
                })

            # Check digital signature
            if not cls.verify_digital_signature(blk["block_hash"], blk.get("digital_signature", "")):
                tampered.append({
                    "block_number": b_num,
                    "reason": "Cryptographic HMAC digital signature is invalid.",
                })

            prev_hash = blk["block_hash"]

        is_valid = len(tampered) == 0
        return {
            "total_blocks": len(sorted_blocks),
            "chain_valid": is_valid,
            "status": "HEALTHY" if is_valid else "COMPROMISED",
            "message": "All blockchain blocks verified with zero anomalies." if is_valid else f"Detected {len(tampered)} chain tampering anomalies!",
            "tampered_blocks": tampered,
            "latest_block_number": sorted_blocks[-1]["block_number"] if sorted_blocks else 0,
            "latest_block_hash": sorted_blocks[-1]["block_hash"] if sorted_blocks else None,
        }
