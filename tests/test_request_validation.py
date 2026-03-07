"""Tests for test request validation."""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi import HTTPException

import utils.request_validation as rv


class DummyUpload:
    def __init__(self, filename: str, payload: bytes):
        self.filename = filename
        self.file = BytesIO(payload)


def test_guess_image_sections_defaults_to_results():
    out = rv.guess_image_sections("photo.png", "lab_report")
    assert out == ["Results"]


def test_validate_template_inputs_rejects_images_when_disabled():
    with pytest.raises(HTTPException) as ex:
        rv.validate_template_inputs(
            template_key="study_guide",
            template_cfg={"form_schema": {"allow_images": False}},
            has_csv=False,
            has_images=True,
            include_review_bool=False,
            goal="ok",
        )
    assert ex.value.status_code == 400
    assert "does not accept image uploads" in str(ex.value.detail)


def test_save_image_uploads_keeps_only_valid_target_sections(monkeypatch):
    monkeypatch.setattr(rv, "save_upload", lambda *_args, **_kwargs: "/tmp/x.png")

    assets = rv.save_image_uploads(
        [DummyUpload("setup.png", b"img")],
        "lab_report",
        template_cfg={"writer_format": ["Results", "Discussion"]},
        image_titles=["setup"],
        image_captions=["caption"],
        image_sections=["NotASection"],
        max_image_uploads=5,
        image_extensions={".png"},
    )
    assert len(assets) == 1
    assert assets[0]["target_section"] == ""
    assert assets[0]["suggested_sections"]


def test_validate_template_inputs_requires_one_of_csv_or_images():
    with pytest.raises(HTTPException) as ex:
        rv.validate_template_inputs(
            template_key="lab_report",
            template_cfg={
                "form_schema": {
                    "allow_csv": True,
                    "allow_images": True,
                    "require_any_of": ["csv", "images"],
                }
            },
            has_csv=False,
            has_images=False,
            include_review_bool=False,
            goal="ok",
        )
    assert ex.value.status_code == 400
    assert "requires at least one data source" in str(ex.value.detail)


def test_save_table_text_data_parses_csv_rows():
    path = rv.save_table_text_data("time,temp\n0,20\n1,22\n")
    assert path.endswith(".csv")
