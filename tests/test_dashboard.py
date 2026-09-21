"""
Tests for Step 10A: Streamlit dashboard safety, architecture, and portfolio README.

Covers all 20 required verification points:
1. app.py exists
2. app.py parses cleanly
3. app imports safely
4. no file uploader
5. no live optimization call
6. no scipy.optimize.milp usage in app.py
7. no BatteryModel.step call
8. no downloader call
9. disclaimer exists
10. perfect-foresight wording exists
11. non-investment-advice wording exists
12. SOH limitation exists
13. 20 EUR nominal scenario displayed
14. dashboard source files exist
15. all five figure files exist
16. dashboard reads saved reports
17. frozen headline metrics are preserved
18. README exists
19. README includes limitations
20. README includes run-local instructions
"""

import ast
from pathlib import Path
import pytest
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_PATH = ROOT_DIR / "app.py"
README_PATH = ROOT_DIR / "README.md"
REPORTS_DIR = ROOT_DIR / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"


# 1. app.py exists
def test_app_file_exists():
    assert APP_PATH.exists(), "app.py must exist in project root"


# 2. app.py parses cleanly
def test_app_parses_cleanly():
    content = APP_PATH.read_text(encoding="utf-8")
    parsed = ast.parse(content)
    assert isinstance(parsed, ast.Module), "app.py should parse into valid AST module"


# 3. app imports safely
def test_app_imports_safely():
    import app
    assert hasattr(app, "load_all_reports")
    assert hasattr(app, "main")


# 4. no file uploader
def test_no_file_uploader_in_app():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "file_uploader" not in content, "Dashboard must be read-only and not accept uploads"


# 5. no live optimization call
def test_no_live_optimization_call():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "solve_day_milp" not in content
    assert "simulate_optimized" not in content
    assert "simulate_baseline" not in content
    assert "solve_day_degradation_milp" not in content


# 6. no scipy.optimize.milp usage in app.py
def test_no_scipy_milp_usage_in_app():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "scipy.optimize" not in content
    assert "milp(" not in content
    assert "MilpResult" not in content


# 7. no BatteryModel.step call
def test_no_batterymodel_step_call_in_app():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "BatteryModel.step" not in content
    assert "BESSModel.step" not in content
    assert "simulate_battery" not in content


# 8. no downloader call
def test_no_downloader_call_in_app():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "download_smard" not in content
    assert "requests.get" not in content
    assert "requests.post" not in content


# 9. disclaimer exists
def test_disclaimer_exists_in_app():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "disclaimer" in content.lower()


# 10. perfect-foresight wording exists
def test_perfect_foresight_wording_exists():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "perfect-foresight" in content.lower() or "perfect foresight" in content.lower()


# 11. non-investment-advice wording exists
def test_non_investment_advice_wording_exists():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "investment advice" in content.lower()


# 12. SOH limitation exists
def test_soh_limitation_exists_in_app():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "state of health" in content.lower() or "soh" in content.lower()
    assert "does not predict" in content.lower() or "no electrochemical" in content.lower()


# 13. 20 EUR nominal scenario displayed
def test_20eur_nominal_scenario_displayed():
    content = APP_PATH.read_text(encoding="utf-8")
    assert "20 EUR" in content or "20.0" in content
    assert "Nominal 20 EUR" in content


# 14. dashboard source files exist
def test_dashboard_source_files_exist():
    required_reports = [
        REPORTS_DIR / "baseline_summary_2024.json",
        REPORTS_DIR / "optimized_summary_2024.json",
        REPORTS_DIR / "degradation_aware_summary_20eur_2024.json",
        REPORTS_DIR / "degradation_sensitivity_2024.csv",
        REPORTS_DIR / "monthly_nominal_performance_2024.csv",
        REPORTS_DIR / "baseline_vs_degradation_aware_daily_20eur_2024.csv",
    ]
    for p in required_reports:
        assert p.exists(), f"Required report file {p.name} missing"


# 15. all five figure files exist
def test_all_five_figure_files_exist():
    figures = [
        "degradation_sensitivity_margin.png",
        "degradation_sensitivity_efc.png",
        "monthly_nominal_performance.png",
        "baseline_vs_nominal_daily.png",
        "representative_day_dispatch.png",
    ]
    for fig in figures:
        p = FIGURES_DIR / fig
        assert p.exists(), f"Figure file {fig} is missing"
        assert p.stat().st_size > 10_000, f"Figure file {fig} is empty"


# 16. dashboard reads saved reports
def test_dashboard_reads_saved_reports():
    import app
    data = app.load_all_reports()
    assert "baseline_summary" in data
    assert "optimized_summary" in data
    assert "deg_summary_20" in data
    assert "df_sensitivity" in data
    assert "df_monthly" in data
    assert "df_daily_20" in data
    assert len(data["df_monthly"]) == 12
    assert len(data["df_sensitivity"]) == 4


# 17. frozen headline metrics are preserved
def test_frozen_headline_metrics_preserved():
    import app
    data = app.load_all_reports()
    assert data["baseline_summary"]["gross_arbitrage_margin_eur"] == pytest.approx(19588.28, rel=1e-4)
    assert data["optimized_summary"]["gross_arbitrage_margin_eur"] == pytest.approx(64831.06, rel=1e-4)
    assert data["deg_summary_20"]["net_margin_after_degradation_eur"] == pytest.approx(44685.44, rel=1e-4)
    assert data["deg_summary_20"]["equivalent_full_cycles"] == pytest.approx(418.30, rel=1e-4)


# 18. README exists
def test_readme_exists():
    assert README_PATH.exists(), "README.md must exist in project root"
    assert README_PATH.stat().st_size > 1_000, "README.md must have substantial content"


# 19. README includes limitations
def test_readme_includes_limitations():
    content = README_PATH.read_text(encoding="utf-8")
    assert "## Limitations" in content
    assert "perfect foresight" in content.lower()
    assert "wholesale energy-only" in content.lower()
    assert "no electrochemical soh model" in content.lower()


# 20. README includes run-local instructions
def test_readme_includes_run_local_instructions():
    content = README_PATH.read_text(encoding="utf-8")
    assert "## Run Locally" in content
    assert ".venv" in content
    assert "streamlit run app.py" in content


# 21. Exact validated baseline schedule wording
def test_exact_baseline_schedule_wording():
    app_text = APP_PATH.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    for text, name in [(app_text, "app.py"), (readme_text, "README.md")]:
        # Required validated schedule hours
        assert "03:00" in text, f"{name} must mention charge at 03:00"
        assert "18:00" in text, f"{name} must mention discharge at 18:00"
        assert "19:00" in text, f"{name} must mention discharge at 19:00"
        assert "23:00" in text, f"{name} must mention charge at 23:00"
        assert "all other hours idle" in text.lower(), f"{name} must state all other hours idle"
        assert "price-blind" in text.lower(), f"{name} must state schedule is price-blind"

        # Forbidden incorrect ranges
        assert "02:00–04:00" not in text, f"{name} must not contain 02:00–04:00"
        assert "13:00–15:00" not in text, f"{name} must not contain 13:00–15:00"
        assert "07:00–09:00" not in text, f"{name} must not contain 07:00–09:00"
        assert "18:00–20:00" not in text, f"{name} must not contain 18:00–20:00"


# 22. Baseline net margin at same 20 EUR assumption
def test_baseline_net_margin_at_same_20eur_assumption():
    app_text = APP_PATH.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    for text, name in [(app_text, "app.py"), (readme_text, "README.md")]:
        assert "11,712.00" in text or "11,712" in text, f"{name} must mention baseline assumed cycling cost €11,712"
        assert "7,876.28" in text or "7,876" in text, f"{name} must mention baseline net margin €7,876"
        assert "36,809" in text, f"{name} must mention net improvement +€36,809"


# 23. No physical wear reduction claims
def test_no_physical_wear_reduction_claims():
    app_text = APP_PATH.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    forbidden = [
        "cycle wear reduction",
        "wear penalty",
        "cycling wear is modeled",
        "gross value per efc jumps",
    ]
    for text, name in [(app_text, "app.py"), (readme_text, "README.md")]:
        for phrase in forbidden:
            assert phrase not in text.lower(), f"{name} contains forbidden phrase: '{phrase}'"


# 24. No guarantee mathematical agreement claims & check consistency wording
def test_methodology_consistency_wording():
    app_text = APP_PATH.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    for text, name in [(app_text, "app.py"), (readme_text, "README.md")]:
        assert "guarantee mathematical and physical agreement" not in text.lower()
        assert "verify mathematical and physical consistency within numerical tolerance" in text.lower()
        assert "batterymodel" in text.lower()
        assert "optimized arbitrage timing" in text.lower()
        assert "intelligent arbitrage timing" not in text.lower()
        assert "physically feasible within the simplified historical benchmark" in text.lower()
