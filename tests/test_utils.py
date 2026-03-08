from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils import build_cl_ord_id, is_managed_cl_ord_id, managed_id_token


def test_build_cl_ord_id_is_alphanumeric_and_short():
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    assert len(cl_ord_id) <= 32
    assert cl_ord_id.isalnum()
    assert cl_ord_id.startswith(managed_id_token("bot6"))


def test_is_managed_cl_ord_id_matches_new_prefix_token():
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    assert is_managed_cl_ord_id(cl_ord_id, "bot6") is True
    assert is_managed_cl_ord_id("manual123", "bot6") is False
