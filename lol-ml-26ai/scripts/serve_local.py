#!/usr/bin/env python
"""A tiny local scoring server with the same request/response contract as the OCI Model Deployment artifact.

    python scripts/serve_local.py --port 8080
    curl -s localhost:8080/predict -d '{"instances": [{"magicresist": 40, "timestamp": 600000, ...}]}'

Response: {"win_probability": [0.55]}. Standard library only; it is for the lab, not for production.
"""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import serving  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8080)
ap.add_argument("--onnx", action="store_true", help="score with onnxruntime instead of scikit-learn")
a = ap.parse_args()
scorer = serving.Scorer(onnx=a.onnx)


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._send(200, {"status": "ok", "features": scorer.features, **{k: scorer.meta[k] for k in ("test_accuracy", "test_auc")}}
                   if self.path == "/health" else {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/predict":
            return self._send(404, {"error": "not found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            probs = scorer.win_probability(req["instances"])
            self._send(200, {"win_probability": [round(float(p), 6) for p in probs]})
        except (KeyError, ValueError, TypeError) as e:
            self._send(400, {"error": f"{type(e).__name__}: {e}", "expected_features": scorer.features})

    def log_message(self, *args):
        pass


print(f"serving {'ONNX' if a.onnx else 'scikit-learn'} model on http://127.0.0.1:{a.port}  (Ctrl+C to stop)")
try:
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
except KeyboardInterrupt:
    pass
