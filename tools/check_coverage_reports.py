"""在 CI 匯入 Sonar 前確認報告非空，且每筆來源都能對應儲存庫中的正式程式。"""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def source_path(name: str, prefix: str) -> Path:
    """報告必須使用可搬移的相對路徑，拒絕容器內絕對路徑與目錄逃逸。"""
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Coverage path must be repository-relative: {name}")
    result = ROOT / prefix / path
    if not result.is_file() or not result.resolve().is_relative_to(ROOT):
        raise ValueError(f"Coverage source does not exist: {prefix}/{name}")
    return result


def check_backend() -> int:
    """Cobertura 必須含可執行列及分支資料；不可把零資料檔當成成功報告。"""
    document = ET.parse(ROOT / "reports/backend-coverage.xml").getroot()
    if int(document.attrib["lines-valid"]) <= 0 or int(document.attrib["branches-valid"]) <= 0:
        raise ValueError("Backend coverage has no lines or branches")
    sources = {element.text for element in document.findall("sources/source")}
    if sources != {"backend"}:
        raise ValueError(f"Unexpected backend source roots: {sources}")
    files = [source_path(element.attrib["filename"], "backend") for element in document.findall(".//class")]
    if not files:
        raise ValueError("Backend coverage has no source files")
    return len(files)


def check_frontend() -> int:
    """LCOV 的每筆來源須從 repo root 解析，包含未被匯入的 Vue 畫面。"""
    report = (ROOT / "frontend/coverage/lcov.info").read_text(encoding="utf-8")
    files = [source_path(line[3:], "") for line in report.splitlines() if line.startswith("SF:")]
    if not files or not any(line.startswith("DA:") for line in report.splitlines()):
        raise ValueError("Frontend coverage has no source files or executable lines")
    expected = set((ROOT / "frontend/src").rglob("*.ts")) | set((ROOT / "frontend/src").rglob("*.vue"))
    if set(files) != expected:
        raise ValueError("Frontend coverage must include every src TypeScript and Vue file")
    return len(files)


def main() -> None:
    """供本機與 CI 共用；失敗時保留例外，讓工作流程明確失敗。"""
    print(f"Coverage paths verified: backend={check_backend()}, frontend={check_frontend()}")


if __name__ == "__main__":
    main()
