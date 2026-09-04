from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from birkin.native.serve_announce import BridgeOwnershipLease


def _signature(token: str, instance_id: str, owner_id: str, expires_at: float) -> str:
    payload = f"{instance_id}\n{owner_id}\n{expires_at:.6f}".encode()
    return hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()


def test_authenticated_claim_transfers_instance_ownership(tmp_path: Path) -> None:
    token = "stable-owner-secret"
    lease = BridgeOwnershipLease(
        tmp_path, instance_id="instance-1", pid=123, token=token,
        now=lambda: 100.0, reclaim_seconds=5.0,
    )
    lease.publish(transport="uds", endpoint=str(tmp_path / "bridge.sock"))
    claim = {
        "instance_id": "instance-1", "owner_id": "app-relaunch",
        "expires_at": 109.0,
    }
    claim["signature"] = _signature(
        token, str(claim["instance_id"]), str(claim["owner_id"]),
        float(claim["expires_at"]),
    )
    _ = lease.claim_path.write_text(json.dumps(claim), encoding="utf-8")

    assert lease.check(now=104.9) is True
    assert lease.owner_id == "app-relaunch"
    assert lease.deadline == 109.0
    print("B3 CLAIM instance=instance-1 owner=app-relaunch accepted=true")


def test_forged_claim_cannot_extend_lease_and_unclaimed_helper_retires(
    tmp_path: Path,
) -> None:
    lease = BridgeOwnershipLease(
        tmp_path, instance_id="instance-1", pid=123, token="real-secret",
        now=lambda: 200.0, reclaim_seconds=5.0,
    )
    lease.publish(transport="uds", endpoint=str(tmp_path / "bridge.sock"))
    forged = {
        "instance_id": "instance-1", "owner_id": "forged", "expires_at": 220.0,
        "signature": _signature("wrong-secret", "instance-1", "forged", 220.0),
    }
    _ = lease.claim_path.write_text(json.dumps(forged), encoding="utf-8")

    assert lease.check(now=204.9) is True
    assert lease.check(now=205.0) is False
    assert lease.owner_id != "forged"
    lease.close()
    assert not lease.record_path.exists()
    assert not lease.claim_path.exists()
    print("B3 RETIRE instance=instance-1 forged_claim=false record_removed=true")
