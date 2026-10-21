"""獨立 UID 的 journal authority；只接受認證的 append/read，不提供歷史刪改。"""
import hmac
import os
from pathlib import Path
import socket
from runtime.budget_types import integer, object_fields
from sealing.journal import JournalStore
from sealing.rpc import receive_frame, send_frame

SOCKET_PATH = "/var/lib/axiom/socket/journal.sock"
SOCKET_GROUP = 10003


def dispatch(request: dict[str,object], store: JournalStore, token: str) -> object:
    """驗證憑證後才讀寫；未知操作與任何失敗都只回遮罩代碼。"""
    if not hmac.compare_digest(str(request.get("token","")),token):
        return {"code":"NOT_FOUND"}
    operation = request.get("op")
    if operation == "health":
        return {"status":"ok"}
    if operation not in {"read","append"}:
        return {"code":"NOT_FOUND"}
    try:
        if operation == "read":
            return {"entries":store.read()}
        return store.append(object_fields(request["payload"]),integer(request["expected"]))
    except (OSError,ValueError,KeyError):
        return {"code":"EXPOSURE_RECOVERY_BLOCKED"}


def serve(connection: socket.socket, store: JournalStore, token: str) -> None:
    """單一連線單一請求；先驗證再讀寫，任何失敗都只回遮罩代碼。"""
    connection.settimeout(5)
    try:
        reply = dispatch(receive_frame(connection),store,token)
    except (OSError,ValueError,KeyError):
        reply = {"code":"EXPOSURE_RECOVERY_BLOCKED"}
    send_frame(connection,reply)


def main() -> None:
    """只在專用 UID 啟動；缺憑證或 socket 路徑異常則拒絕服務。"""
    if os.getuid()!=10004:
        raise SystemExit('Dedicated journal UID required')
    token = os.environ.get('AXIOM_JOURNAL_TOKEN','')
    if len(token)<32:
        raise SystemExit('Journal credential missing')
    path = Path(os.environ.get('AXIOM_JOURNAL_SOCKET',SOCKET_PATH))
    if not path.is_absolute():
        raise SystemExit('Journal socket path must be absolute')
    store = JournalStore(Path('/var/lib/axiom/journal'),Path('/var/lib/axiom/authority'))
    if path.exists():
        path.unlink()
    listener = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    listener.bind(str(path))
    os.chown(path,-1,SOCKET_GROUP)
    os.chmod(path,0o660)
    listener.listen(8)
    while True:
        connection,_ = listener.accept()
        with connection:
            serve(connection,store,token)


if __name__=='__main__':
    main()
