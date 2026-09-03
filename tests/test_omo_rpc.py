from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import birkin.omo_rpc as omo_rpc
from birkin.omo_rpc import OmoRpcClient


def test_rpc_client_uses_jsonl_protocol() -> None:
    program = """import json,sys\nfor line in sys.stdin:\n request=json.loads(line); data={'text':'done'} if request['type']=='get_last_assistant_text' else {}; print(json.dumps({'id':request['id'],'type':'response','success':True,'data':data}),flush=True); print(json.dumps({'type':'agent_settled'}),flush=True)"""
    client = OmoRpcClient(
        command=(sys.executable, "-u", "-c", program),
        timeout=5,
    )
    try:
        client.switch_session(Path("C:/sessions/example.jsonl"))
        assert client.prompt("hello") == "done"
        client.steer("change direction")
        client.abort()
    finally:
        client.close()


def test_rpc_client_kills_process_tree_after_close_timeout(monkeypatch) -> None:
    class HungProcess:
        stdin = None
        waits = 0

        def poll(self) -> None:
            return None

        def wait(self, timeout: float) -> None:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("omo", timeout)

    process = HungProcess()
    killed: list[HungProcess] = []
    client = OmoRpcClient(command=("omo",))
    client.__dict__["_process"] = process
    monkeypatch.setattr(
        omo_rpc,
        "kill_tree",
        lambda selected: killed.append(selected),
        raising=False,
    )

    client.close()

    assert killed == [process]
