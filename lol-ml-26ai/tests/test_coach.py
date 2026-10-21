"""Plain-script tests: percentile maths and prompt on real rows, request format against a local stub server.
The stub only checks the HTTP request shape (URL path, bearer header, JSON body). It says nothing about the LLM's answers.
Run:  python tests/test_coach.py"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import coach, data  # noqa: E402

perf = data.load("performance")


def test_percentiles_and_prompt():
    row = perf.iloc[0]
    rep = coach.percentile_report(row, perf)
    assert len(rep) == 6 and all(0 <= r["percentile"] <= 100 for r in rep)
    msgs = coach.build_messages(row["championName"], row["teamPosition"], row["duration"], bool(row["win"]), 0.62, rep)
    assert "Use ONLY the numbers" in msgs[0]["content"] and row["championName"] in msgs[1]["content"]
    # a player with far more deaths per minute than everybody must score a LOW death percentile
    bad = perf[perf.teamPosition == "TOP"].iloc[0].copy()
    bad["deaths"] = 60
    assert [r for r in coach.percentile_report(bad, perf) if r["stat"] == "deaths per minute"][0]["percentile"] <= 2


def test_request_shape():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            seen["path"], seen["auth"] = self.path, self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"choices": [{"message": {"content": "stub reply"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 29992), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        out = coach.ask([{"role": "user", "content": "hi"}], url="http://127.0.0.1:29992/20231130/actions/v1/chat/completions", key="sk-test")
    finally:
        srv.shutdown()
    assert out == "stub reply" and seen["auth"] == "Bearer sk-test" and seen["body"]["messages"][0]["content"] == "hi"
    assert coach.endpoint("us-chicago-1") == "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130/actions/v1/chat/completions"


if __name__ == "__main__":
    test_percentiles_and_prompt()
    print("PASS test_percentiles_and_prompt")
    test_request_shape()
    print("PASS test_request_shape")
