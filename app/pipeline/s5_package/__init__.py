"""Stage 5: Packaging, metadata, thumbnails, and credit block."""

from app.pipeline.s5_package.credit import build_credit_block
from app.pipeline.s5_package.metadata import Metadata, generate_metadata
from app.pipeline.s5_package.package import package_clip, run

__all__ = ["Metadata", "build_credit_block", "generate_metadata", "package_clip", "run"]
