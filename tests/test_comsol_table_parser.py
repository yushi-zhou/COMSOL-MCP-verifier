from __future__ import annotations

import pytest

from em_design_mcp.parsers.comsol_table_parser import parse_comsol_table_text


def test_parse_five_column_comsol_table_groups_by_wavelength() -> None:
    text = """
% l lam freq T psi
55 800 3.7e14 0.82 1.2
50 750 4.0e14 0.90 0.1
55 750 4.0e14 0.91 0.2
50 800 3.7e14 0.81 1.1
"""
    output = parse_comsol_table_text(text, wavelengths_nm=[750, 800])

    assert output["data_by_lam"]["750"]["param_nm"] == [50, 55]
    assert output["data_by_lam"]["750"]["T"] == [0.9, 0.91]
    assert output["data_by_lam"]["800"]["phi_rad"] == [1.1, 1.2]
    assert output["summary_metrics"]["mean_transmission"] == pytest.approx(0.86)


def test_parse_four_column_comsol_table_for_single_wavelength() -> None:
    text = """
% l freq T psi
50 4.0e14 0.90 0.1
55 4.0e14 0.91 0.2
"""
    output = parse_comsol_table_text(text, wavelengths_nm=[750])

    assert output["data_by_lam"] == {
        "750": {
            "param_nm": [50, 55],
            "T": [0.9, 0.91],
            "phi_rad": [0.1, 0.2],
        }
    }


def test_parse_comsol_table_snaps_only_small_wavelength_drift() -> None:
    text = """
% l lam freq T psi
50 749.9999999999999 4.0e14 0.90 0.1
"""

    output = parse_comsol_table_text(
        text,
        wavelengths_nm=[750],
        wavelength_match_tolerance_nm=0.001,
    )

    assert output["data_by_lam"]["750"]["T"] == [0.9]


def test_parse_comsol_table_rejects_wavelength_outside_match_tolerance() -> None:
    text = """
% l lam freq T psi
50 760 4.0e14 0.90 0.1
"""

    with pytest.raises(ValueError, match="exceeding tolerance 0.001 nm"):
        parse_comsol_table_text(
            text,
            wavelengths_nm=[750, 800],
            wavelength_match_tolerance_nm=0.001,
        )


def test_parse_comsol_table_rejects_invalid_wavelength_tolerance() -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        parse_comsol_table_text(
            "50 750 4.0e14 0.90 0.1",
            wavelengths_nm=[750],
            wavelength_match_tolerance_nm=-1,
        )


def test_parse_comsol_table_rejects_empty_table() -> None:
    with pytest.raises(ValueError, match="No numeric"):
        parse_comsol_table_text("% header only")
