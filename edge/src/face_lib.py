import json
import logging
import os
import hashlib
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Student:
    def __init__(self, student_id: str, name: str, photo_path: str):
        self.student_id = student_id
        self.name = name
        self.photo_path = photo_path


class FaceLib:
    """人脸库管理：扫描目录、预提取特征向量、变化检测。"""

    def __init__(self, face_lib_path: str):
        self.base_path = Path(face_lib_path)
        self.students_path = self.base_path / "students.json"
        self.photos_path = self.base_path / "photos"
        self.embeddings_path = self.base_path / "embeddings"
        self.students: list[Student] = []
        self.embeddings: dict[str, "np.ndarray"] = {}  # student_id → feature vector
        self._photos_hash: str = ""

    def load_roster(self) -> list[Student]:
        raw = json.loads(self.students_path.read_text())
        self.students = [
            Student(s["student_id"], s["name"], str(self.base_path / s["photo"]))
            for s in raw
        ]
        logger.info("FaceLib roster loaded: %d students", len(self.students))
        return self.students

    def _compute_photos_hash(self) -> str:
        """计算 photos/ 目录下所有文件的哈希，用于变化检测。"""
        hasher = hashlib.sha256()
        if not self.photos_path.exists():
            return ""
        for f in sorted(self.photos_path.iterdir()):
            if f.is_file():
                hasher.update(f.read_bytes())
                hasher.update(str(f.stat().st_mtime).encode())
        return hasher.hexdigest()

    def need_rebuild(self) -> bool:
        current_hash = self._compute_photos_hash()
        if current_hash != self._photos_hash:
            self._photos_hash = current_hash
            return True
        return False

    async def rebuild_embeddings(self, extractor: "FaceEngine") -> None:
        """重新提取所有学生的人脸特征向量，缓存到 embeddings/。"""
        import numpy as np

        self.load_roster()
        self.embeddings_path.mkdir(parents=True, exist_ok=True)
        self.embeddings.clear()

        for student in self.students:
            npy_path = self.embeddings_path / f"{student.student_id}.npy"
            photo_path = Path(student.photo_path)

            if not photo_path.exists():
                logger.warning("Photo not found: %s", photo_path)
                continue

            image_bytes = photo_path.read_bytes()
            try:
                feature = await extractor.extract_features(image_bytes)
                np.save(str(npy_path), feature)
                self.embeddings[student.student_id] = feature
                logger.info("Embedding built: %s (%s)", student.name, student.student_id)
            except Exception as e:
                logger.error("Failed to extract features for %s: %s", student.name, e)

        self._photos_hash = self._compute_photos_hash()

    async def load_embeddings_cache(self) -> None:
        """从 embeddings/ 加载缓存的 .npy 文件到内存。"""
        import numpy as np

        self.load_roster()
        self.embeddings.clear()

        for student in self.students:
            npy_path = self.embeddings_path / f"{student.student_id}.npy"
            if npy_path.exists():
                self.embeddings[student.student_id] = np.load(str(npy_path))

        logger.info("FaceLib embeddings loaded from cache: %d/%d students",
                     len(self.embeddings), len(self.students))

    async def init(self, extractor: "FaceEngine") -> None:
        """加载花名册，必要时重建特征库。"""
        if self.need_rebuild():
            logger.info("FaceLib: photos changed, rebuilding embeddings...")
            await self.rebuild_embeddings(extractor)
        else:
            await self.load_embeddings_cache()
