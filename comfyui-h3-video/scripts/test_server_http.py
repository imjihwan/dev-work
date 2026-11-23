"""서버 핸들러를 실제 소켓(127.0.0.1 의 임시 포트)으로 시험한다.

합성 응답만 쓴다. ComfyUI·실행 중인 화면 서버(8190)·사용자 데이터에는 연결하지 않는다.
확인하는 것: 다른 사이트가 보낸 POST 거절, 너무 큰 본문 거절, ComfyUI 거절 사유 전달,
내려받기 이름의 헤더 안전성, 보내는 도중 실패했을 때 두 번째 응답을 섞지 않는 것, 잘못된 요청에서 기록이 죽지 않는 것.
"""
import ast
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import pathlib
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
from unittest import mock

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "simple_ui" / "server.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def rejection(code, payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return urllib.error.HTTPError("http://synthetic/prompt", code, "Bad Request", {}, io.BytesIO(body))


class Upstream:
    """ComfyUI /view 응답 흉내. fail_after 를 주면 그만큼 보낸 뒤 읽기가 실패한다(quiet 이면 예외 없이 끝난다)."""
    def __init__(self, data, fail_after=None, status=200, quiet=False, length=True):
        self.data, self.sent, self.fail_after, self.status, self.quiet = data, 0, fail_after, status, quiet
        self.headers = {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"}
        if length:
            self.headers["Content-Length"] = str(len(data))
        self.closed = False

    def read(self, size=-1):
        if self.fail_after is not None and self.sent >= self.fail_after:
            if self.quiet:
                return b""
            raise http.client.IncompleteRead(b"")
        end = len(self.data) if size < 0 else self.sent + size
        if self.fail_after is not None:
            end = min(end, self.fail_after)
        chunk = self.data[self.sent:end]
        self.sent += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


class ServerHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        here = pathlib.Path(self.tmp.name)
        (here / "index.html").write_text("synthetic page", encoding="utf-8")
        self.logs, self.generated = [], []
        self.status_result = lambda pid: {"state": "queued", "id": pid}
        self.generate_result = lambda body: {"ok": True}
        self.upstream = lambda path, data, headers: Upstream(b"synthetic-video")
        handler = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "H")
        helper = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "comfy_rejection")

        def build(body):
            self.generated.append(body)
            return self.generate_result(body)
        self.env = {"BaseHTTPRequestHandler": BaseHTTPRequestHandler, "json": json, "os": os, "urllib": urllib,
                    "HERE": str(here), "INDEX": str(here / "index.html"),
                    "print": lambda *args, **kwargs: self.logs.append(" ".join(str(arg) for arg in args)),
                    "status": lambda pid: self.status_result(pid), "build_and_queue": build,
                    "comfy": lambda path, data=None, headers=None: self.upstream(path, data, headers)}
        exec(compile(ast.Module(body=[helper, handler], type_ignores=[]), "<synthetic-server>", "exec"), self.env)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.env["H"])
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        environment = mock.patch.dict(os.environ, {}, clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("SIMPLEUI_TRUSTED_ORIGINS", "SIMPLEUI_MAX_BODY_MB"):
            os.environ.pop(name, None)

    def connection(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(connection.close)
        return connection

    def call(self, method, path, body=None, headers=None, connection=None):
        connection = connection or self.connection()
        raw = None if body is None else json.dumps(body).encode()
        connection.request(method, path, raw, {"Content-Type": "application/json", **(headers or {})} if raw is not None else headers or {})
        response = connection.getresponse()
        data = response.read()
        return response, data

    def post(self, path, body, **headers):
        response, data = self.call("POST", path, body, headers)
        return response.status, json.loads(data)

    # ---- 다른 사이트가 보낸 POST ----
    def test_post_without_origin_and_same_origin_posts_are_accepted(self):
        host = f"127.0.0.1:{self.port}"
        self.assertEqual(self.post("/api/generate", {"n": 1}), (200, {"ok": True}))          # 스크립트·내부 호출
        self.assertEqual(self.post("/api/generate", {"n": 2}, Origin=f"http://{host}"), (200, {"ok": True}))
        self.assertEqual(self.post("/api/generate", {"n": 3}, Origin=f"HTTP://{host.upper()}/"), (200, {"ok": True}))
        self.assertEqual([body["n"] for body in self.generated], [1, 2, 3])

    def test_cross_site_post_is_refused_before_the_body_is_used(self):
        for origin in ("https://example.invalid", "http://127.0.0.1:1", "null", "file://", f"http://evil.127.0.0.1:{self.port}"):
            with self.subTest(origin=origin):
                status, answer = self.post("/api/generate", {"n": 1}, Origin=origin)
                self.assertEqual(status, 403)
                self.assertIn("다른 사이트", answer["error"])
        self.assertEqual(self.generated, [])

    def test_refused_post_closes_the_connection_so_the_unread_body_cannot_become_a_request(self):
        connection = self.connection()
        smuggled = b"GET /api/status?id=smuggled HTTP/1.1\r\nHost: x\r\n\r\n"
        connection.request("POST", "/api/generate", smuggled, {"Origin": "https://example.invalid"})
        asked = []
        self.status_result = lambda pid: asked.append(pid) or {"state": "queued", "id": pid}
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        self.assertTrue(response.will_close)
        self.assertIsNone(connection.sock)             # http.client 가 닫힌 연결로 처리했다
        self.assertEqual((self.generated, asked), ([], []))   # 본문 속 요청은 실행되지 않았다

    def test_browser_marked_cross_site_post_without_origin_is_refused(self):
        self.assertEqual(self.post("/api/generate", {"n": 1}, **{"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.post("/api/generate", {"n": 2}, **{"Sec-Fetch-Site": "same-site"})[0], 403)
        self.assertEqual(self.post("/api/generate", {"n": 5}, **{"Sec-Fetch-Site": ""})[0], 403)   # 빈 값도 '있음'
        self.assertEqual(self.post("/api/generate", {"n": 3}, **{"Sec-Fetch-Site": "same-origin"})[0], 200)
        host = f"127.0.0.1:{self.port}"
        self.assertEqual(self.post("/api/generate", {"n": 4}, Origin=f"http://{host}", **{"Sec-Fetch-Site": "same-origin"})[0], 200)
        self.assertEqual([body["n"] for body in self.generated], [3, 4])

    def test_proxy_host_and_explicitly_trusted_origins_are_accepted(self):
        proxied = {"Origin": "https://video.example.test", "X-Forwarded-Host": "video.example.test"}
        self.assertEqual(self.post("/api/generate", {"n": 1}, **proxied)[0], 200)
        self.assertEqual(self.post("/api/generate", {"n": 2}, Origin="https://video.example.test")[0], 403)
        os.environ["SIMPLEUI_TRUSTED_ORIGINS"] = "https://other.example.test, https://video.example.test/"
        self.assertEqual(self.post("/api/generate", {"n": 3}, Origin="https://video.example.test")[0], 200)
        os.environ["SIMPLEUI_TRUSTED_ORIGINS"] = "*"
        self.assertEqual(self.post("/api/generate", {"n": 4}, Origin="https://anything.example.test")[0], 200)
        self.assertEqual([body["n"] for body in self.generated], [1, 3, 4])

    def test_default_ports_compare_equal(self):
        handler = self.env["H"].__new__(self.env["H"])
        for origin, host, expected in (("http://pc.example.test", "pc.example.test:80", True),
                                       ("https://pc.example.test:443", "pc.example.test", True),
                                       ("http://pc.example.test:8190", "pc.example.test", False),
                                       ("https://pc.example.test", "pc.example.test:80", False),     # 다른 포트
                                       ("http://pc.example.test:443", "pc.example.test", False),
                                       ("http://pc.example.test:0", "pc.example.test", False),       # 0 은 '포트 없음'이 아니다
                                       ("http://pc.example.test", "pc.example.test:0", False),
                                       ("http://PC.Example.Test.:8190", "pc.example.test:8190", True),  # 대소문자·끝의 점
                                       ("http://[::1]:8190", "[::1]:8190", True),
                                       ("http://[::1]:8190", "[::2]:8190", False),
                                       ("http://[bad", "pc.example.test", False),                    # 형식 오류는 거절(예외 없음)
                                       ("http://pc.example.test:port", "pc.example.test", False),
                                       ("ftp://pc.example.test", "pc.example.test", False),
                                       ("null", "pc.example.test", False)):
            with self.subTest(origin=origin, host=host):
                handler.headers = {"Host": host}
                self.assertIs(handler._same_origin(origin), expected)

    # ---- 본문 크기 ----
    def test_oversized_or_invalid_length_is_refused_without_reading(self):
        os.environ["SIMPLEUI_MAX_BODY_MB"] = "1"
        for length, expected in ((str(2 * 1024 * 1024), 413), ("-5", 400), ("many", 400)):
            with self.subTest(length=length):
                with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
                    raw.sendall(f"POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: {length}\r\n\r\n".encode())
                    answer = raw.makefile("rb").read()   # 서버가 연결을 닫아야 끝난다
                self.assertTrue(answer.startswith(f"HTTP/1.1 {expected} ".encode()), answer[:40])
        self.assertEqual(self.generated, [])
        self.assertEqual(self.post("/api/generate", {"fits": True})[0], 200)

    def raw(self, request):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as connection:
            connection.sendall(request)
            return connection.makefile("rb").read()   # 서버가 연결을 닫아야 끝난다

    def test_ambiguous_body_framing_is_refused_and_never_dispatched(self):
        chunked = b"POST /api/generate HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n5\r\n{\"a\":\r\n2\r\n1}\r\n0\r\n\r\n"
        doubled = b"POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\nContent-Length: 30\r\n\r\n{}"
        empty = b"POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: \r\n\r\n"
        signed = b"POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: +2\r\n\r\n{}"
        blank_encoding = b"POST /api/generate HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: \r\nContent-Length: 2\r\n\r\n{}"
        superscript = "POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: \u00b2\r\n\r\n{}".encode("latin-1")
        endless = b"POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: " + b"9" * 5000 + b"\r\n\r\n{}"
        for request in (chunked, doubled, empty, signed, blank_encoding, superscript, endless):
            with self.subTest(request=request[:70]):
                answer = self.raw(request)
                self.assertTrue(answer.startswith(b"HTTP/1.1 400 "), answer[:40])
                self.assertEqual(answer.count(b"HTTP/1.1 "), 1)   # 남은 바이트가 두 번째 요청으로 처리되지 않았다
        self.assertEqual(self.generated, [])
        # 본문 없는 POST(길이 헤더 없음)는 지금처럼 받는다
        self.assertTrue(self.raw(b"POST /api/generate HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").startswith(b"HTTP/1.1 200 "))
        self.assertEqual(self.generated, [{}])

    def test_expect_continue_still_gets_the_final_error_response(self):
        # curl·PowerShell 은 큰 POST 에 'Expect: 100-continue' 를 붙인다. 중간 응답 뒤의 오류도 최종 응답으로 답해야 한다.
        def refuse(body):
            raise ValueError("합성 거절 사유")
        self.generate_result = refuse
        body = b'{"n": 1}'
        head = f"POST /api/generate HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n".encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as connection:
            connection.sendall(head)
            reader = connection.makefile("rb")
            self.assertEqual(reader.readline(), b"HTTP/1.1 100 Continue\r\n")
            self.assertEqual(reader.readline(), b"\r\n")
            connection.sendall(body)
            final = reader.read()
        self.assertTrue(final.startswith(b"HTTP/1.1 400 "), final[:60])
        self.assertIn("합성 거절 사유".encode(), final)

    def test_refused_cross_site_post_is_answered_even_if_the_body_never_arrives(self):
        started = time.monotonic()
        answer = self.raw(b"POST /api/generate HTTP/1.1\r\nHost: x\r\nOrigin: https://example.invalid\r\nContent-Length: 500000\r\n\r\npartial")
        self.assertTrue(answer.startswith(b"HTTP/1.1 403 "))
        self.assertLess(time.monotonic() - started, 4)   # 버려야 할 본문을 끝없이 기다리지 않는다

    # ---- 오류 문구 ----
    def test_comfy_validation_failure_is_reported_with_its_reason_not_as_a_connection_failure(self):
        payload = {"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation", "details": ""},
                   "node_errors": {"12": {"class_type": "UNETLoader", "errors": [
                       {"type": "value_not_in_list", "message": "Value not in list", "details": "unet_name: 'missing.safetensors' not in ['a']"}]}}}

        def refuse(body):
            raise rejection(400, payload)
        self.generate_result = refuse
        status, answer = self.post("/api/generate", {"n": 1})
        self.assertEqual(status, 502)
        self.assertIn("HTTP 400", answer["error"])
        self.assertIn("UNETLoader", answer["error"])
        self.assertIn("missing.safetensors", answer["error"])
        self.assertNotIn("연결할 수 없습니다", answer["error"])

    def test_unreachable_comfy_is_still_reported_as_a_connection_failure(self):
        def down(body):
            raise urllib.error.URLError(ConnectionRefusedError(10061, "synthetic refusal"))
        self.generate_result = down
        status, answer = self.post("/api/generate", {"n": 1})
        self.assertEqual(status, 502)
        self.assertIn("ComfyUI(8188)에 연결할 수 없습니다", answer["error"])

    def test_rejection_text_tolerates_odd_bodies_and_bounds_long_details(self):
        describe = self.env["comfy_rejection"]
        self.assertIn("HTTP 500", describe(rejection(500, b"<html>not json</html>")))
        self.assertIn("HTTP 400", describe(urllib.error.HTTPError("http://synthetic", 400, "Bad", {}, None)))
        self.assertIn("plain reason", describe(rejection(400, {"error": "plain reason"})))
        long = describe(rejection(400, {"error": {"message": "m" * 900, "details": "x" * 900},
                                        "node_errors": {str(n): {"class_type": "N" * 200, "errors": [{"message": "e" * 900, "details": "y" * 900}] * 3} for n in range(6)}}))
        self.assertIn("NNN", long)             # 한도(200KB) 안의 본문이라 실제로 조립된 문구다
        self.assertLessEqual(len(long), 1200)  # 앞머리까지 포함한 한 줄 전체의 한도
        for odd in ({"error": None, "node_errors": ["unexpected"]}, {"node_errors": {"1": {"errors": 1}}},
                    {"node_errors": {"1": 5, "2": {"errors": [None, "x", {"message": 7}]}}}, [1, 2], "text", None):
            with self.subTest(odd=odd):
                self.assertIn("HTTP 400", describe(rejection(400, odd)))
        closing = rejection(400, {"error": "x"})
        describe(closing)
        self.assertTrue(closing.fp is None or closing.fp.closed)

    def test_error_text_drops_the_known_folder_prefixes_and_nothing_else(self):
        text = self.env["H"]._error_text
        home = os.path.expanduser("~")
        comfy = os.path.dirname(self.env["HERE"])          # 화면 서버 폴더의 부모 = ComfyUI 폴더
        self.assertGreater(len(home), 3)
        inside = os.path.join(comfy, "input", "my photo.png")
        under_home = os.path.join(home, "Some Folder", "clip.mp4")
        cases = ((f"Invalid image file: {inside}", os.path.join("input", "my photo.png")),
                 (f"failed {inside!r} (retry/skip)", "my photo.png"),                      # repr: 역슬래시가 겹쳐 적힌다
                 (f"cannot open {inside.replace(os.sep, '/')} now", "input/my photo.png"),
                 (f"열 수 없습니다: {under_home.upper()}", "CLIP.MP4"),                      # 대소문자가 달라도
                 (f"mixed {home.replace(os.sep, '/', 1)}{os.sep}Some Folder/clip.mp4", "Some Folder/clip.mp4"),   # 구분자가 섞여도
                 (f"only the folder: {comfy}", "only the folder: "),
                 (f"{under_home} 을 열 수 없습니다(다시 시도 / 건너뛰기)", "clip.mp4 을 열 수 없습니다(다시 시도 / 건너뛰기)"))
        for message, kept in cases:
            with self.subTest(message=message):
                shown = text(ValueError(message))
                for secret in (home, comfy, home.replace("\\", "/"), home.replace("\\", "\\\\")):
                    self.assertNotIn(secret.lower(), shown.lower())
                self.assertIn(kept, shown)
        # 이름이 이어지는 이웃 폴더는 다른 폴더다
        sibling = f"Failed to open {comfy}-backup{os.sep}models{os.sep}clip.safetensors"
        self.assertIn("-backup", text(sibling))
        self.assertIn(os.path.basename(comfy) + "-backup", text(sibling))
        # 아는 폴더가 아니면 추측해서 고치지 않는다: 경로처럼 보이는 글·주소·다른 드라이브는 그대로다
        for unchanged in ("모델 파일이 목록에 없습니다: MiniMaxH3\\model.safetensors", "ComfyUI(8188)에 연결할 수 없습니다: [WinError 10061] 거부",
                          "see http://127.0.0.1:8188/view?filename=a.png and https://example.test/a/b/c", "길이는 1~15초 사이로 정해 주세요(H3 최대 15초).",
                          "비율 9:16 / 720p", "작업 3/5", "빠르게 / 보통 / 품질", "https://example.test/?next=/private/video.mp4&x=/a/b",
                          "Could not open Q:\\models\\clip.safetensors (retry/skip)", "http://lan:8188/view?filename=@/models/clip.mp4"):
            with self.subTest(unchanged=unchanged):
                self.assertEqual(text(unchanged), unchanged)
        self.assertEqual(text("깨진 글자 \udcff 끝"), "깨진 글자 ? 끝")

    def test_get_errors_use_fitting_codes_and_never_expose_server_paths(self):
        private = os.path.join(self.tmp.name, "private-folder", "project.json")
        cases = ((ValueError("작업 ID를 확인해 주세요."), 400, "작업 ID를 확인해 주세요."),
                 (FileNotFoundError(2, "No such file or directory", private), 500, "project.json"),
                 (KeyError("queue_running"), 500, "queue_running"),
                 (RuntimeError(), 500, "RuntimeError"))
        for error, code, expected in cases:
            with self.subTest(error=type(error).__name__):
                def fail(pid, error=error):
                    raise error
                self.status_result = fail
                response, data = self.call("GET", "/api/status?id=x")
                answer = json.loads(data)["error"]
                self.assertEqual(response.status, code)
                self.assertIn(expected, answer)
                self.assertNotIn("private-folder", answer)
                self.assertNotIn(self.tmp.name, answer)

    def test_missing_status_id_is_explained(self):
        response, data = self.call("GET", "/api/status")
        self.assertEqual(response.status, 500)
        self.assertIn("id", json.loads(data)["error"])

    # ---- 내려받기 이름 ----
    def test_download_name_is_header_safe_and_keeps_korean_names(self):
        name = "결과 영상\r\nSet-Cookie: injected=1\".mp4"
        query = urllib.parse.urlencode({"filename": name, "subfolder": "video", "type": "output", "download": "1"})
        response, data = self.call("GET", "/api/video?" + query)
        self.assertEqual(response.status, 200)
        self.assertEqual(data, b"synthetic-video")
        self.assertIsNone(response.getheader("Set-Cookie"))
        disposition = response.getheader("Content-Disposition")
        self.assertTrue(disposition.startswith('attachment; filename="'))
        self.assertNotIn("\r", disposition)
        self.assertNotIn("\n", disposition)
        encoded = disposition.split("filename*=UTF-8''", 1)[1]
        self.assertEqual(urllib.parse.unquote(encoded), "결과 영상Set-Cookie: injected=1.mp4")
        disposition.encode("latin-1")   # 헤더로 보낼 수 있는 글자만

    def test_download_name_drops_folders_and_has_a_fallback(self):
        attachment = self.env["H"]._attachment
        self.assertIn('filename="clip.mp4"', attachment("..\\..\\private/clip.mp4"))
        self.assertIn('filename="video.mp4"', attachment(None))
        self.assertIn('filename="video.mp4"', attachment("folder/"))

    # ---- 보내는 도중 실패 ----
    def test_upstream_failure_mid_stream_closes_instead_of_appending_a_second_response(self):
        payload = b"x" * 200000
        streams = []

        def broken(path, data, headers):
            streams.append(Upstream(payload, fail_after=70000))
            return streams[-1]
        self.upstream = broken
        connection = self.connection()
        connection.request("GET", "/api/video?filename=a.mp4&subfolder=&type=output")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        with self.assertRaises(http.client.IncompleteRead) as caught:
            response.read()
        self.assertEqual(caught.exception.partial, payload[:70000])   # JSON 오류 문구가 영상 바이트 뒤에 붙지 않는다
        self.assertTrue(streams[0].closed)

    def test_upstream_that_ends_early_without_an_error_also_closes_the_connection(self):
        payload = b"x" * 200000
        self.upstream = lambda path, data, headers: Upstream(payload, fail_after=70000, quiet=True)
        connection = self.connection()
        connection.request("GET", "/api/video?filename=a.mp4&subfolder=&type=output")
        response = connection.getresponse()
        with self.assertRaises(http.client.IncompleteRead) as caught:
            response.read()
        self.assertEqual(len(caught.exception.partial), 70000)

    def test_upstream_without_a_length_is_delimited_by_closing(self):
        self.upstream = lambda path, data, headers: Upstream(b"synthetic-video", length=False)
        response, data = self.call("GET", "/api/video?filename=a.mp4&subfolder=&type=output")
        self.assertEqual((response.status, data), (200, b"synthetic-video"))
        self.assertTrue(response.will_close)

    def test_range_response_keeps_status_and_headers(self):
        seen = []

        def ranged(path, data, headers):
            seen.append(headers)
            stream = Upstream(b"synth", status=206)
            stream.headers["Content-Range"] = "bytes 0-4/15"
            return stream
        self.upstream = ranged
        response, data = self.call("GET", "/api/video?filename=a.mp4&subfolder=&type=output", headers={"Range": "bytes=0-4"})
        self.assertEqual((response.status, data), (206, b"synth"))
        self.assertEqual(response.getheader("Content-Range"), "bytes 0-4/15")
        self.assertEqual(seen, [{"Range": "bytes=0-4"}])
        self.assertFalse(response.will_close)

    def test_connection_is_reused_after_a_complete_response(self):
        connection = self.connection()
        first, _ = self.call("GET", "/api/status?id=one", connection=connection)
        second, data = self.call("GET", "/api/status?id=two", connection=connection)
        self.assertFalse(first.will_close)
        self.assertEqual((second.status, json.loads(data)["id"]), (200, "two"))

    # ---- 잘못된 요청 ----
    def test_non_http_bytes_get_an_error_and_do_not_break_logging(self):
        for garbage in (b"\x16\x03\x01\x02\x00\x01\x00\x01\xfc\x03\x03" + b"\x00" * 40 + b"\r\n\r\n", b"GARBAGE\r\n\r\n"):
            with self.subTest(garbage=garbage[:8]):
                with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
                    raw.sendall(garbage)
                    answer = raw.makefile("rb").read()
                self.assertIn(b" 400 ", answer.split(b"\r\n", 1)[0])
        self.assertTrue(any("알 수 없는 요청" in line for line in self.logs), self.logs)
        self.assertEqual(self.call("GET", "/api/status?id=after")[0].status, 200)   # 서버는 계속 응답한다

    def test_frequent_polls_stay_out_of_the_log_and_other_requests_are_logged_by_path_only(self):
        self.call("GET", "/api/status?id=quiet")
        self.post("/api/generate", {"prompt": "PRIVATE TEXT"})
        self.assertEqual(self.call("GET", "/unknown/page?name=PRIVATE-NAME")[0].status, 404)
        self.assertTrue(self.raw(b"BREW /api/input?name=PRIVATE-NAME HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").startswith(b"HTTP/1.1 501 "))
        self.assertEqual(self.logs, ["POST /api/generate", "GET /unknown/page", "BREW /api/input"])

    def test_malformed_request_target_is_answered_with_400(self):
        answer = self.raw(b"GET http://[bad/api/status HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertTrue(answer.startswith(b"HTTP/1.1 400 "), answer[:60])


if __name__ == "__main__":
    unittest.main()
