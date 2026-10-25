import httpx
import pytest

moto_server = pytest.importorskip("moto.server")

from app.config import load_settings
from app.storage import S3Storage


def test_s3_upload_and_presigned_download(tmp_path):
    import socket
    with socket.socket() as sk:  # pick a free port ourselves
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    host = "127.0.0.1"
    srv = moto_server.ThreadedMotoServer(ip_address=host, port=port, verbose=False)
    srv.start()
    import time
    for _ in range(50):  # wait until the emulator accepts connections
        try:
            httpx.get(f"http://{host}:{port}/", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    try:
        s = load_settings(data_dir=str(tmp_path), storage_backend="s3", s3_endpoint=f"http://{host}:{port}",
                          s3_bucket="test-bucket", s3_access_key="k", s3_secret_key="k")
        st = S3Storage(s)
        assert st.ready()
        f = tmp_path / "a.json"
        f.write_text('{"ok": true}')
        url = st.put_file("job_1/a.json", str(f))
        assert httpx.get(url).json() == {"ok": True}
    finally:
        srv.stop()
