"""
Tests for the two fixes applied to _response_processing.py and types/metadata.py:

Fix 1 – process_block_response must use model_validate / parse_obj so that
         camelCase alias keys from the API are properly mapped to snake_case
         Pydantic field names, instead of calling cast_to(**data) which bypasses
         alias resolution.

Fix 2 – BaseMetadata.name must be Optional[str] because the API returns
         "name": null for the root-level folder entry.
"""

import json
from unittest.mock import MagicMock, patch
from unittest.mock import MagicMock, patch

import httpx
import pytest

from aidial_client._exception import ParsingDataError
from aidial_client._utils._response_processing import process_block_response
from aidial_client.types.metadata import BaseMetadata, FileItem, FileMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Exact payload returned by the real API (from the bug report)
REAL_API_PAYLOAD = {
    "bucket": "684f6Lz7ubje66aoCRsa5c",
    "items": [
        {
            "bucket": "684f6Lz7ubje66aoCRsa5c",
            "items": None,
            "name": "appdata",
            "nodeType": "FOLDER",
            "parentPath": None,
            "resourceType": "FILE",
            "url": "files/684f6Lz7ubje66aoCRsa5c/appdata/",
        },
        {
            "bucket": "684f6Lz7ubje66aoCRsa5c",
            "contentLength": 2207949,
            "contentType": "application/pdf",
            "name": "ontologies.pdf",
            "nodeType": "ITEM",
            "parentPath": None,
            "resourceType": "FILE",
            "updatedAt": 1770130629876,
            "url": "files/684f6Lz7ubje66aoCRsa5c/ontologies.pdf",
        },
    ],
    "name": None,  # <-- root folder has null name (Fix 2)
    "nodeType": "FOLDER",  # <-- camelCase alias (Fix 1)
    "parentPath": None,
    "resourceType": "FILE",
    "url": "files/684f6Lz7ubje66aoCRsa5c/",
}


def _make_response(payload: dict, status_code: int = 200) -> httpx.Response:
    """Build a minimal httpx.Response carrying a JSON body."""
    raw = json.dumps(payload).encode()
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": "application/json"},
        content=raw,
    )


# ===========================================================================
# Fix 1 – process_block_response resolves camelCase aliases
# ===========================================================================


class TestProcessBlockResponseAliasResolution:
    """
    Before the fix, cast_to(**data) was called.  With camelCase keys coming
    from the API, Pydantic's __init__ (which expects snake_case field names)
    would raise a ValidationError or silently ignore the fields.
    After the fix, model_validate / parse_obj is used and aliases are handled.
    """

    def test_file_metadata_camel_case_parsed_correctly(self):
        response = _make_response(REAL_API_PAYLOAD)
        result = process_block_response(FileMetadata, response)

        assert isinstance(result, FileMetadata)
        assert result.node_type == "FOLDER"
        assert result.resource_type == "FILE"
        assert result.bucket == "684f6Lz7ubje66aoCRsa5c"
        assert result.url == "files/684f6Lz7ubje66aoCRsa5c/"
        assert result.parent_path is None

    def test_nested_items_are_parsed(self):
        response = _make_response(REAL_API_PAYLOAD)
        result = process_block_response(FileMetadata, response)

        assert result.items is not None
        assert len(result.items) == 2

        folder_item = result.items[0]
        assert isinstance(folder_item, FileItem)
        assert folder_item.name == "appdata"
        assert folder_item.node_type == "FOLDER"

        file_item = result.items[1]
        assert isinstance(file_item, FileItem)
        assert file_item.name == "ontologies.pdf"
        assert file_item.node_type == "ITEM"
        assert file_item.content_length == 2207949
        assert file_item.content_type == "application/pdf"

    def test_invalid_json_body_raises_parsing_data_error(self):
        """process_block_response wraps parse failures in ParsingDataError."""
        bad_payload = {"nodeType": "FOLDER", "resourceType": "INVALID_TYPE"}
        response = _make_response(bad_payload)
        with pytest.raises(ParsingDataError):
            process_block_response(FileMetadata, response)

    def test_returns_httpx_response_when_cast_to_is_response(self):
        response = _make_response(REAL_API_PAYLOAD)
        result = process_block_response(httpx.Response, response)
        assert result is response

    def test_returns_bytes_when_cast_to_is_bytes(self):
        response = _make_response({"x": 1})
        result = process_block_response(bytes, response)
        assert isinstance(result, bytes)

    def test_returns_str_when_cast_to_is_str(self):
        response = _make_response({"x": 1})
        result = process_block_response(str, response)
        assert isinstance(result, str)


# ===========================================================================
# Fix 2 – BaseMetadata.name is Optional[str]
# ===========================================================================


class TestBaseMetadataOptionalName:
    """
    Before the fix, name: str caused a ValidationError when the API returned
    "name": null for root-folder metadata entries.
    """

    def test_name_none_is_accepted(self):
        """Root-folder entries come back with name=null; this must not raise."""
        meta = BaseMetadata(
            name=None,
            bucket="abc",
            url="files/abc/",
            node_type="FOLDER",
            resource_type="FILE",
        )
        assert meta.name is None

    def test_name_str_still_works(self):
        meta = BaseMetadata(
            name="my-file.pdf",
            bucket="abc",
            url="files/abc/my-file.pdf",
            node_type="ITEM",
            resource_type="FILE",
        )
        assert meta.name == "my-file.pdf"

    def test_name_defaults_to_none_when_omitted(self):
        meta = BaseMetadata(
            bucket="abc",
            url="files/abc/",
            node_type="FOLDER",
            resource_type="FILE",
        )
        assert meta.name is None

    def test_file_metadata_name_none_via_model_validate(self):
        """End-to-end: parse the real API payload – name=null must not fail."""
        result = (
            FileMetadata.model_validate(REAL_API_PAYLOAD)
            if hasattr(FileMetadata, "model_validate")
            else FileMetadata.parse_obj(REAL_API_PAYLOAD)
        )  # type: ignore[attr-defined]

        assert result.name is None

    def test_file_metadata_full_real_payload(self):
        """The full payload from the bug report must parse without error."""
        response = _make_response(REAL_API_PAYLOAD)
        result = process_block_response(FileMetadata, response)
        assert result.name is None
        assert result.bucket == "684f6Lz7ubje66aoCRsa5c"


# ===========================================================================
# Branch coverage – model_validate (v2) vs parse_obj (v1)
# ===========================================================================

_MODULE = "aidial_client._utils._response_processing"


class TestProcessBlockResponsePydanticBranch:
    """
    The project supports pydantic>=1.10,<3 so both branches must be exercised.
    These tests mock PYDANTIC_V2 to force each path regardless of which
    Pydantic version is actually installed.
    """

    def test_pydantic_v2_branch_calls_model_validate(self):
        """When PYDANTIC_V2 is True, model_validate must be used."""
        response = _make_response(REAL_API_PAYLOAD)
        expected = MagicMock(spec=FileMetadata)

        with patch(f"{_MODULE}.PYDANTIC_V2", True):
            with patch.object(
                FileMetadata, "model_validate", return_value=expected
            ) as mock_validate:
                result = process_block_response(FileMetadata, response)

        mock_validate.assert_called_once_with(REAL_API_PAYLOAD)
        assert result is expected

    def test_pydantic_v1_branch_calls_parse_obj(self):
        """When PYDANTIC_V2 is False (Pydantic v1 installed), parse_obj must be used."""
        response = _make_response(REAL_API_PAYLOAD)
        expected = MagicMock(spec=FileMetadata)

        with patch(f"{_MODULE}.PYDANTIC_V2", False):
            with patch.object(
                FileMetadata, "parse_obj", return_value=expected, create=True
            ) as mock_parse:
                result = process_block_response(FileMetadata, response)

        mock_parse.assert_called_once_with(REAL_API_PAYLOAD)
        assert result is expected

