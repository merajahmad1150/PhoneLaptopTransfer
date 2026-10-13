"""TEST-ONLY stand-in for waitress.server.create_server (sandbox has no internet). Accepts the same
tuning names real waitress 3 accepts, and rejects unknown ones with ValueError like waitress does."""
from werkzeug.serving import make_server
_KNOWN = {"threads","recv_bytes","send_bytes","inbuf_overflow","outbuf_overflow","max_request_body_size",
          "channel_timeout","connection_limit","backlog","asyncore_use_poll"}
class _S:
    def __init__(self, s): self.s = s
    def run(self): self.s.serve_forever()
    def close(self): self.s.shutdown(); self.s.server_close()
def create_server(app, host="0.0.0.0", port=8080, **kw):
    bad = set(kw) - _KNOWN
    if bad: raise ValueError(f"Unknown adjustment {bad}")
    return _S(make_server(host, port, app, threaded=True))
