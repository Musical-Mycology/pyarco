import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parent.parent


def test_cli_generates_output(tmp_path):
    output = tmp_path / "arco_generated.py"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "ugen2py.py"),
         str(FIXTURES), "-o", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert output.exists()

    content = output.read_text()
    assert "# AUTO-GENERATED" in content
    assert "class Sine(Ugen):" in content
    assert "class Sineb(Ugen):" in content
    assert "class Lowpass(Ugen):" in content
    assert "class Overdrive(Ugen):" in content
    assert "class Sttest(Ugen):" in content
    assert "class Noisegate(Ugen):" in content


def test_cli_prints_summary(tmp_path):
    output = tmp_path / "arco_generated.py"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "ugen2py.py"),
         str(FIXTURES), "-o", str(output)],
        capture_output=True, text=True,
    )
    assert "Generated" in result.stdout
    assert "classes" in result.stdout


def test_arco_import_hook_exists():
    """Verify arco.py has the generated import at the bottom."""
    arco_path = PROJECT_ROOT / "python25" / "arco.py"
    content = arco_path.read_text()
    assert "from arco_generated import *" in content
