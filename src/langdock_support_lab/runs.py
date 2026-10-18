import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4
from .adapters import synthetic
from .adapters.langdock import attempt
from .adapters.base import observation
from .errors import LabError


def utc_now():
    return datetime.now(timezone.utc)


def stamp(clock):
    return clock().isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Runs:
    def __init__(self, config, storage, clock=utc_now, monotonic=time.monotonic, uuid=uuid4, transport=None):
        self.config, self.storage = config, storage
        self.clock, self.monotonic, self.uuid, self.transport = clock, monotonic, uuid, transport
        self.active = 0
        self.scenarios = synthetic.registry(config.root)

    async def create(self, request):
        if request.mode != self.config.mode:
            raise LabError("MODE_MISMATCH", 409)
        scenario = getattr(request, "scenario_id", None)
        if request.mode == "offline" and not any(row["id"] == scenario and request.operation in row["operations"] for row in self.scenarios):
            raise LabError("INVALID_INPUT")
        if self.active >= 4:
            raise LabError("LOCAL_CAPACITY", 503)
        self.active += 1
        run = {"id": str(self.uuid()), "created_at": stamp(self.clock), "finished_at": None,
               "mode": request.mode, "provenance": "synthetic" if request.mode == "offline" else "live",
               "operation": request.operation, "scenario_id": scenario,
               "probe_id": "health-text" if request.operation == "agent_completion" else "runbook-auth", "status": "running", "observation": None}
        inserted = False
        start = self.monotonic()
        try:
            await asyncio.to_thread(self.storage.insert_run, run)
            inserted = True
            if request.mode == "offline":
                key = None if scenario == "auth-missing" else "synthetic-invalid" if scenario == "auth-invalid" else "synthetic-valid"
                transport = self.transport if self.transport is not None else synthetic.transport(self.config.root, scenario, request.operation)
                agent = "lab-agent"
            else:
                key, agent, transport = self.config.provider_key, self.config.agent_id, self.transport
            result = await attempt(request.operation, run["id"], key, agent, transport, self.clock, self.config.deadline)
            result["duration_ms"] = max(0, int((self.monotonic() - start) * 1000))
            run.update(finished_at=stamp(self.clock), observation=result, status="succeeded" if result["code"] in ("OK", "OK_EMPTY") else "failed")
            await asyncio.to_thread(self.storage.finalize_run, run)
            return run
        except asyncio.CancelledError:
            if inserted:
                run.update(finished_at=stamp(self.clock), status="interrupted", observation=observation("RUN_INTERRUPTED"))
                try:
                    async with asyncio.timeout(1):
                        await asyncio.shield(asyncio.to_thread(self.storage.finalize_run, run))
                except (TimeoutError, LabError):
                    pass
            raise
        finally:
            self.active -= 1
