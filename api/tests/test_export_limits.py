"""Tests de los candados de export (tope de filas 413 y tope de bytes)."""

import zipfile

import pytest
from fastapi import HTTPException

from app.routers import export
from app.services import exporter
from app.settings import settings


# ---------------------------------------------------------------------------
# Tope de filas (413) — función aislada, sin DB.
# ---------------------------------------------------------------------------

def test_row_cap_rechaza_sobre_limite(monkeypatch):
    monkeypatch.setattr(settings, "export_max_rows", 1000)
    with pytest.raises(HTTPException) as exc:
        export._enforce_row_cap(1001)
    assert exc.value.status_code == 413
    # Mensaje en español y accionable.
    assert "limite" in exc.value.detail.lower()
    assert "fechas" in exc.value.detail.lower()


def test_row_cap_permite_en_el_limite(monkeypatch):
    monkeypatch.setattr(settings, "export_max_rows", 1000)
    # Exactamente en el límite: permitido (no lanza).
    export._enforce_row_cap(1000)
    export._enforce_row_cap(0)


# ---------------------------------------------------------------------------
# Tope de bytes — medición del ZIP en disco y corte.
# ---------------------------------------------------------------------------

def test_zip_bytes_written_crece(tmp_path):
    zip_path = tmp_path / "x.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        antes = exporter._zip_bytes_written(zf, zip_path)
        zf.writestr("a.txt", "x" * 100_000)
        despues = exporter._zip_bytes_written(zf, zip_path)
        assert despues > antes
        assert despues >= 100_000


def test_corte_por_bytes_lanza_y_borra_zip(tmp_path, monkeypatch):
    """Simula el bucle real: tras escribir un grupo, si el ZIP supera el tope
    se lanza ExportTooLargeError y se borra el ZIP parcial."""
    monkeypatch.setattr(settings, "export_max_bytes", 50_000)
    zip_path = tmp_path / "job.zip"
    payload_file = tmp_path / "big.csv"
    payload_file.write_text("d" * 200_000, encoding="utf-8")

    with pytest.raises(exporter.ExportTooLargeError) as exc:
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                zf.write(payload_file, "big.csv")
                written = exporter._zip_bytes_written(zf, zip_path)
                if written > settings.export_max_bytes:
                    raise exporter.ExportTooLargeError(
                        f"La exportacion supero el limite de "
                        f"{settings.export_max_bytes} bytes."
                    )
        except exporter.ExportTooLargeError:
            zip_path.unlink(missing_ok=True)
            raise
    assert "limite" in str(exc.value).lower()
    # El ZIP parcial NO debe quedar en disco.
    assert not zip_path.exists()


def test_run_job_safe_marca_failed_en_corte(monkeypatch):
    """El wrapper convierte ExportTooLargeError en estado 'failed' con mensaje."""
    captured = {}

    def fake_run_job(job_id):
        raise exporter.ExportTooLargeError("La exportacion supero el limite de bytes.")

    def fake_update(job_id, **fields):
        captured.update(fields)

    monkeypatch.setattr(exporter, "_run_job", fake_run_job)
    monkeypatch.setattr(exporter, "_update", fake_update)

    exporter._run_job_safe("abc")
    assert captured["status"] == "failed"
    assert "limite" in captured["error"].lower()
