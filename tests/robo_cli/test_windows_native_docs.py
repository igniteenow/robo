from pathlib import Path


def test_windows_native_install_path_docs_match_installer() -> None:
    doc = Path("website/docs/user-guide/windows-native.md").read_text()
    install = Path("scripts/install.ps1").read_text()

    assert "%LOCALAPPDATA%\\robo\\robo-engineer\\venv\\Scripts" in doc
    assert "Get-Command robo        # should print C:\\Users\\<you>\\AppData\\Local\\robo\\robo-engineer\\venv\\Scripts\\robo.exe" in doc
    assert '$roboBin = "$InstallDir\\venv\\Scripts"' in install
