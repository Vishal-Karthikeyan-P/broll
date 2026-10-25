"""Output storage: local disk (default) or any S3-compatible store (MinIO in compose)."""
from __future__ import annotations

import mimetypes
import os
import shutil

from .config import Settings


class LocalStorage:
    def __init__(self, s: Settings):
        self.root = os.path.join(s.data_dir, "outputs")
        self.base = s.public_base_url
        os.makedirs(self.root, exist_ok=True)

    def put_file(self, key: str, path: str) -> str:
        dest = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(path, dest)
        return f"{self.base}/api/v1/files/{key}"

    def local_path(self, key: str) -> str | None:
        p = os.path.normpath(os.path.join(self.root, key))
        return p if p.startswith(os.path.normpath(self.root) + os.sep) and os.path.isfile(p) else None

    def ready(self) -> bool:
        return os.access(self.root, os.W_OK)


class S3Storage:
    def __init__(self, s: Settings):
        import boto3
        from botocore.client import Config

        cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"})
        kw = dict(aws_access_key_id=s.s3_access_key, aws_secret_access_key=s.s3_secret_key,
                  region_name=s.s3_region, config=cfg)
        self.bucket = s.s3_bucket
        self.client = boto3.client("s3", endpoint_url=s.s3_endpoint or None, **kw)
        # Presigned links must use the address clients can reach (may differ from the internal one).
        self.signer = boto3.client("s3", endpoint_url=(s.s3_public_endpoint or s.s3_endpoint) or None, **kw)
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except Exception:
                pass

    def put_file(self, key: str, path: str) -> str:
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.client.upload_file(path, self.bucket, key, ExtraArgs={"ContentType": ctype})
        return self.signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=7 * 24 * 3600)

    def local_path(self, key: str) -> str | None:
        return None

    def ready(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def build_storage(s: Settings):
    return S3Storage(s) if s.storage_backend == "s3" else LocalStorage(s)
