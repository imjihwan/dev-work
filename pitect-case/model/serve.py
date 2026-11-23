#!/usr/bin/env python3
"""PI-TECT 모델 생성 페이지용 로컬 서버. 사용: python3 model/serve.py  →  http://localhost:8765/
페이지가 만든 STL을 ../models/ 폴더에 저장한다. 127.0.0.1에서만 받는다."""
import http.server, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(ROOT), 'models')

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def do_POST(self):
        m = re.fullmatch(r'/save/([A-Za-z0-9_-]+\.(?:stl|json))', self.path)
        n = int(self.headers.get('Content-Length', '0'))
        if not m or n > 60_000_000:
            self.send_error(400)
            return
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, m.group(1)), 'wb') as f:
            f.write(self.rfile.read(n))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f'http://localhost:{port}/', flush=True)
    http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
