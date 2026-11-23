"""설치 복사 목록·소스 배포 허용 목록·공개 템플릿이 저장소의 실제 파일과 맞는지 확인한다.

파일을 읽기만 한다. 설치·다운로드·실행은 하지 않는다. 지키려는 것:
- 화면 서버가 쓰는 파일이 설치 복사 목록에서 빠지면 새 PC 에서 서버가 켜지지 않는다(실제로 production_chat.py 가 빠져 있었다).
- 새 파일을 만들고 배포 허용 목록에 넣지 않으면 공개 소스에서 조용히 빠진다.
- 공개 템플릿에는 프롬프트·참조 사진이 남아 있으면 안 된다.
"""
import ast
import copy
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_source_release as release  # noqa: E402

UI = ROOT / "simple_ui"
STATE_FILES = {"cards.json", "presets.json", "history.json", "saved-settings.json", "ui-state.json", "production-chat.json"}


def ui_sources():
    """화면 서버 폴더의 소스 파일(PC 별 상태 파일·캐시는 제외)."""
    names = set()
    for path in UI.iterdir():
        if not path.is_file() or path.name in STATE_FILES or path.suffix == ".tmp":
            continue
        if path.suffix in (".py", ".html", ".js", ".bat") or path.name.endswith(".seed.json") or path.name == "template_api.json":
            names.add(path.name)
    return names


def setup_copy_list():
    text = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8-sig")
    block = re.search(r"\$publicUiFiles\s*=\s*@\((.*?)\)", text, re.S).group(1)
    return re.findall(r"'([^']+)'", block), text


class SetupManifestTests(unittest.TestCase):
    def test_setup_copies_every_ui_source_file_exactly_once(self):
        copied, _ = setup_copy_list()
        self.assertEqual(len(copied), len(set(copied)), "중복 항목")
        self.assertEqual(set(copied), ui_sources(), "setup.ps1 의 $publicUiFiles 와 simple_ui 의 소스 파일이 다르다")
        self.assertEqual(set(copied), set(release.UI_FILES), "설치 복사 목록과 배포 허용 목록(UI_FILES)이 다르다")

    def test_every_module_the_server_imports_and_every_script_a_page_loads_is_copied(self):
        copied = set(setup_copy_list()[0])
        for path in UI.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
                for module in modules:
                    local = module.split(".")[0] + ".py"
                    if (UI / local).is_file():
                        self.assertIn(local, copied, f"{path.name} 이(가) 불러오는 {local} 이 설치 복사 목록에 없다")
        server = (UI / "server.py").read_text(encoding="utf-8-sig")
        for page in UI.glob("*.html"):
            for source in re.findall(r'<script\s+src="/([^"]+)"', page.read_text(encoding="utf-8-sig")):
                # 서버가 그 주소로 내보내는 실제 파일(예: /production-assistant.js → production_assistant.js)
                served = re.search(r'u\.path == "/%s":\s*\n\s*self\._page\(os\.path\.join\(HERE,"([^"]+)"\)' % re.escape(source), server)
                self.assertIsNotNone(served, f"{page.name} 이(가) 불러오는 /{source} 를 서버가 내보내지 않는다")
                self.assertIn(served.group(1), copied)

    def test_ui_is_copied_before_optional_downloads_and_those_downloads_cannot_abort_setup(self):
        _, text = setup_copy_list()
        copy_at = text.index("$publicUiFiles")
        for installer in ("install_face_detector.py", "install_person_detector.py"):
            at = text.index(installer)
            self.assertGreater(at, copy_at, f"{installer} 가 화면 복사보다 먼저 실행된다")
            line_end = text.index("\n", text.index("$LASTEXITCODE", at))
            self.assertIn("Write-Warning", text[at:line_end])
            self.assertNotIn("throw", text[at:line_end])

    def test_powershell_files_keep_the_encoding_windows_powershell_needs(self):
        setup = (ROOT / "scripts" / "setup.ps1").read_bytes()
        self.assertTrue(setup.startswith(b"\xef\xbb\xbf"), "setup.ps1 은 UTF-8 BOM 이 있어야 PowerShell 5.1 이 한글을 깨뜨리지 않는다")
        for path in [ROOT / "scripts" / "setup.ps1", *ROOT.glob("*.ps1")]:
            data = path.read_bytes()
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), f"{path.name}: 줄바꿈은 CRLF")
            if path.parent == ROOT:
                self.assertTrue(data.isascii(), f"{path.name}: BOM 없는 파일에는 ASCII 만")

    def test_complete_models_fetches_required_files_unless_all_is_requested(self):
        text = (ROOT / "Complete-Models.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$All", text)
        self.assertRegex(text, r"if \(\$All\) \{ \$taskArguments \+= '--all' \}")
        self.assertEqual(text.count("'--all'"), 1)


def load_script(name):
    spec = importlib.util.spec_from_file_location("manifest_" + name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ComfyLocationTests(unittest.TestCase):
    """README 의 위치 규칙: --comfy → <프로젝트>\\ComfyUI → %USERPROFILE%\\ComfyUI. 없는 폴더를 새로 만들지 않는다."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)

    def test_default_follows_the_documented_rule(self):
        for name in ("install_person_detector", "install_queue_pause"):
            module = load_script(name)
            with self.subTest(script=name), mock.patch.object(module, "ROOT", self.base):
                self.assertEqual(module.default_comfy(), pathlib.Path.home() / "ComfyUI")
                (self.base / "ComfyUI").mkdir(exist_ok=True)
                self.assertEqual(module.default_comfy(), self.base / "ComfyUI")
                (self.base / "ComfyUI").rmdir()
        for name in ("install_person_detector", "install_queue_pause", "install_local_translator", "restart_backend"):
            source = (ROOT / "scripts" / (name + ".py")).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"default=\s*(ROOT|root)\s*/\s*['\"]ComfyUI['\"]\s*\)", f"{name}: 프로젝트 폴더만 기본값으로 쓰면 규칙과 어긋난다")

    def test_installers_refuse_a_folder_that_is_not_comfyui_and_create_nothing(self):
        missing = self.base / "not-installed" / "ComfyUI"
        detector = load_script("install_person_detector")
        with mock.patch.object(detector.urllib.request, "urlopen", side_effect=AssertionError("No download expected")):
            with self.assertRaises(SystemExit):
                detector.install(missing)
        translator = load_script("install_local_translator")
        with mock.patch.object(sys, "argv", ["install_local_translator.py", "--comfy", str(missing)]), \
                mock.patch.object(translator.subprocess, "run", side_effect=AssertionError("Nothing may be installed")):
            with self.assertRaises(SystemExit):
                translator.main()
        self.assertEqual(list(self.base.iterdir()), [], "엉뚱한 곳에 폴더를 만들면 다른 스크립트가 그 빈 폴더를 설치본으로 고른다")

    def test_translator_reuses_the_helper_runtime_without_fetching_the_helper_model(self):
        source = (ROOT / "scripts" / "install_local_translator.py").read_text(encoding="utf-8")
        self.assertNotIn("Qwen3.5-2B", source, "삭제한 2B 모델 유무로 판단하면 매번 5GB 도우미 모델을 받으러 간다")
        self.assertIn('"--engine", "runtime"', source)
        helper = (ROOT / "scripts" / "install_prompt_helper.py").read_text(encoding="utf-8")
        self.assertIn('"runtime"', helper)

    def test_pid_bookkeeping_cannot_abort_a_restart_after_the_backend_was_stopped(self):
        tree = ast.parse((ROOT / "scripts" / "restart_backend.py").read_text(encoding="utf-8"))
        guarded = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and "comfyui.pid" in ast.unparse(node.body):
                names = [ast.unparse(handler.type) for handler in node.handlers if handler.type is not None]
                guarded = "OSError" in names and "mkdir" in ast.unparse(node.body)
        self.assertTrue(guarded, "logs 폴더가 없어도 PID 기록 실패가 대기열 복원을 중단시키면 안 된다")
        self.assertEqual(ast.unparse(tree).count("comfyui.pid"), 1)


class SourceReleaseTests(unittest.TestCase):
    def expected(self):
        files = {".gitignore", ".gitattributes", "AGENTS.md", "README.md", "CHANGELOG.md", "TODO.md", "models.json", "versions.json", "requirements-test.txt"}
        files |= {path.name for path in ROOT.glob("*.ps1")}
        files |= {"simple_ui/" + name for name in ui_sources()}
        files |= {"docs/" + path.name for path in (ROOT / "docs").glob("*.md")}
        files |= {"scripts/" + path.name for path in (ROOT / "scripts").iterdir()
                  if path.is_file() and path.suffix in (".py", ".cjs", ".ps1", ".bat")}
        files |= {path.relative_to(ROOT).as_posix() for folder in ("extensions", "third_party") for path in (ROOT / folder).rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts and path.suffix in (".py", ".md", ".txt")}
        return files

    def test_allow_list_matches_the_source_files_in_the_repository(self):
        listed = set(release.PUBLIC_FILES)
        self.assertEqual(len(listed), len(release.PUBLIC_FILES), "중복 항목")
        self.assertEqual(sorted(self.expected() - listed), [], "배포 허용 목록에서 빠진 소스 파일")
        self.assertEqual(sorted(listed - self.expected()), [], "허용 목록에 있지만 저장소에 없는 파일")

    def test_every_listed_file_passes_the_release_checks(self):
        for relative in release.PUBLIC_FILES:
            path = ROOT / relative
            with self.subTest(file=relative):
                self.assertTrue(path.is_file())
                self.assertTrue(path.name in (".gitignore", ".gitattributes") or path.suffix in release.ALLOWED_SUFFIXES)
                data = path.read_bytes()
                self.assertLess(len(data), 2_000_000)
                self.assertIsNone(release.SECRET.search(data.decode("utf-8-sig")))

    def test_public_template_is_empty_in_every_place_a_prompt_or_photo_is_mirrored(self):
        template = json.loads((UI / "template_api.json").read_text(encoding="utf-8-sig"))
        release.check_template(template)   # 저장소의 틀은 통과한다
        director = next(key for key, node in template.items() if node.get("class_type") == "MiniMaxH3Director")

        def leaked(change):
            dirty = copy.deepcopy(template)
            inputs = dirty[director]["inputs"]
            timeline, builder = json.loads(inputs["timeline_data"]), json.loads(inputs["builder_state"])
            change(inputs, timeline, builder)
            inputs["timeline_data"], inputs["builder_state"] = json.dumps(timeline), json.dumps(builder)
            return dirty
        leaks = {
            "prompt": lambda i, t, b: i.update(prompt="synthetic private text"),
            "resolved_prompt": lambda i, t, b: t.update(resolved_prompt="synthetic private text"),
            "timeline builder": lambda i, t, b: t["builder_state"].update(simple_prompt="synthetic private text"),
            "continuation": lambda i, t, b: t["continuity"].update(continuation_prompt="synthetic private text"),
            "idea": lambda i, t, b: t["continuity"].update(idea="synthetic private text"),
            "builder": lambda i, t, b: b.update(simple_prompt="synthetic private text"),
            "photo": lambda i, t, b: t.update(items=[{"type": "image", "value": "synthetic.png"}]),
        }
        for name, change in leaks.items():
            with self.subTest(leak=name), self.assertRaises(ValueError):
                release.check_template(leaked(change))
        with self.assertRaises(ValueError):
            release.check_template({"1": {"class_type": "SomethingElse", "inputs": {}}})


if __name__ == "__main__":
    unittest.main()
