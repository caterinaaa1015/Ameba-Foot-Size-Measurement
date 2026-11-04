"""Small durable record store for the AI foot-measurement dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid


class MeasurementLedger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.records = self._read()

    def _read(self):
        if not self.path.is_file():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"無法讀取量測紀錄：{self.path}：{error}") from error
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError(f"量測紀錄格式不正確：{self.path}")
        return value

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.records, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def create(self, subject_name, subject_id, note, result, coin_denomination, measurement_path):
        record = {
            "id": uuid.uuid4().hex,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "subject_name": subject_name.strip() or "未命名",
            "subject_id": subject_id.strip(),
            "note": note.strip(),
            "foot_length_mm": round(float(result["foot_length_mm"]), 1),
            "coin_denomination": int(coin_denomination),
            "measurement_path": str(measurement_path),
        }
        self.records.insert(0, record)
        self._write()
        return record

    def update_identity(self, record_id, subject_name, subject_id, note):
        for record in self.records:
            if record["id"] == record_id:
                record.update({"subject_name": subject_name.strip() or "未命名",
                               "subject_id": subject_id.strip(), "note": note.strip()})
                self._write()
                return record
        raise ValueError("找不到要編輯的量測紀錄。")
