"""Bounded queue edits with grouped readback; no worker interruption or retries."""
import copy
import json
import os
import urllib.error
import urllib.parse


class BuildCache:
    """Only lives for one bulk request. Never caches queued jobs globally."""
    def __init__(self):
        self.values = {}

    def get(self, key, read):
        if key not in self.values:
            self.values[key] = read()
        return copy.deepcopy(self.values[key])


class QueueBulkEditor:
    def __init__(self, request, queue_lock, recovery_dir, save, commit):
        self.request = request
        self.lock = queue_lock
        self.directory = recovery_dir
        self.save = save
        self.commit = commit

    def backup_path(self, pid):
        return os.path.join(self.directory, urllib.parse.quote(pid, safe="") + ".json")

    def state(self):
        with self.request("/queue") as response:
            return json.load(response)

    def history_row(self, pid):
        with self.request("/history/" + urllib.parse.quote(pid, safe="")) as response:
            return (json.load(response).get(pid) or {}).get("prompt")

    def find(self, state, pid):
        return next((row for row in state["queue_running"] + state["queue_pending"] if row[1] == pid), None)

    def job_status(self, pid):
        """Small native status response, with a safe fallback for older ComfyUI."""
        try:
            with self.request("/api/jobs/" + urllib.parse.quote(pid, safe="")) as response:
                value = json.load(response)
            if value.get("id") == pid and value.get("status") in ("pending", "in_progress", "completed", "failed"):
                return value["status"]
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            try:
                value = json.load(exc)
            except (ValueError, TypeError):
                value = None
            if value == {"error": "Job not found"}:
                return "absent"
        # Do not interpret an unsupported endpoint or an unfamiliar response as absence.
        state = self.state()
        if any(row[1] == pid for row in state["queue_running"]):
            return "in_progress"
        if any(row[1] == pid for row in state["queue_pending"]):
            return "pending"
        return "completed" if self.history_row(pid) else "absent"

    def post(self, body):
        with self.request("/prompt", json.dumps(body).encode(), {"Content-Type": "application/json"}) as response:
            result = json.load(response)
        if result.get("error") or result.get("prompt_id") != body["prompt_id"]:
            raise ValueError("ComfyUI가 수정 요청을 수락하지 않았습니다.")
        return result

    def apply(self, changes):
        """At most 25 staged graphs. Hold the app's edit lock until commit/readback."""
        if len(changes) > 25:
            raise ValueError("일괄 수정 묶음이 너무 큽니다.")
        accepted, failed = [], []
        with self.lock:
            state = self.state()
            pending = {row[1]: row for row in state["queue_pending"]}
            running = {row[1] for row in state["queue_running"]}
            for change in changes:
                pid = change["id"]
                old = pending.get(pid)
                if old is None or pid in running:
                    failed.append({"id": pid, "error": "이미 시작됐거나 대기열에서 빠진 항목입니다."})
                    continue
                if old[2] != change["before"]:
                    failed.append({"id": pid, "error": "적용 중 다른 수정이 감지됐습니다. 다시 적용해 주세요."})
                    continue
                path = self.backup_path(pid)
                try:
                    if self.job_status(pid) != "pending":
                        raise ValueError("이미 시작됐거나 대기열에서 빠진 항목입니다.")
                    # Retain the original and the proposed history until both native
                    # readback AND the history checkpoint are durable.
                    original = {"number": old[0], "prompt_id": pid, "prompt": old[2], "extra_data": old[3]}
                    journal = {**original, "replacement": change["prompt"], "history_after": change["entry"]}
                    os.makedirs(self.directory, exist_ok=True)
                    self.save(path, journal)
                    if old[2] == change["prompt"]:
                        accepted.append(change)
                        continue
                    with self.request("/queue", json.dumps({"delete": [pid]}).encode(), {"Content-Type": "application/json"}):
                        pass
                    if self.job_status(pid) != "absent":
                        # Deletion lost a race to the worker. Never requeue or interrupt it.
                        os.remove(path)
                        raise ValueError("수정하는 동안 생성이 시작됐습니다. 실행 중인 작업은 변경하지 않았습니다.")
                    try:
                        self.post({**original, "prompt": change["prompt"]})
                    except (OSError, ValueError) as exc:
                        # An accepted POST can lose its response. Inspect before any
                        # restoration; blind restoration would duplicate a live job.
                        observed = self.state()
                        row = self.find(observed, pid) or self.history_row(pid)
                        if row is not None and row[2] == change["prompt"]:
                            accepted.append(change)
                            continue
                        if row is None:
                            try:
                                self.post(original)
                                restored = self.find(self.state(), pid) or self.history_row(pid)
                                if restored is None or restored[2] != old[2]:
                                    raise ValueError("원본 복원 내용 대조에 실패했습니다.")
                            except (OSError, ValueError) as restore_error:
                                raise ValueError("복원 여부를 확인하지 못했습니다. 복구 사본을 보관했습니다.") from restore_error
                        if row is not None and row[2] != old[2]:
                            raise ValueError("반영 상태가 달라 복구 사본을 보관했습니다.") from exc
                        # A failed update must never replay its proposed history on startup.
                        self.save(path, original)
                        os.remove(path)
                        raise ValueError("수정에 실패해 원래 대기 항목을 유지했습니다.") from exc
                    accepted.append(change)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    failed.append({"id": pid, "error": str(exc)})

            verified = []
            if accepted:
                try:
                    observed = self.state()
                except (OSError, ValueError) as exc:
                    failed.extend({"id": c["id"], "error": "반영 확인에 실패했습니다. 복구 사본을 보관했습니다."} for c in accepted)
                else:
                    by_id = {row[1]: row for row in observed["queue_running"] + observed["queue_pending"]}
                    for change in accepted:
                        try:
                            row = by_id.get(change["id"]) or self.history_row(change["id"])
                            if row is None or row[2] != change["prompt"]:
                                raise ValueError("반영 내용이 일치하지 않아 완료로 처리하지 않았습니다. 복구 사본을 보관했습니다.")
                            verified.append(change)
                        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                            failed.append({"id": change["id"], "error": str(exc)})
            if verified:
                self.commit(verified)
                for change in verified:
                    try:
                        os.remove(self.backup_path(change["id"]))
                    except OSError:
                        pass
            return verified, failed

    def recover(self, entries):
        """Recover only confirmed metadata after a crash; never submit a queued job."""
        if not os.path.isdir(self.directory):
            return 0
        staged = []
        for name in os.listdir(self.directory):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.directory, name), encoding="utf-8") as handle:
                    record = json.load(handle)
                entry = record.get("history_after")
                pid = record.get("prompt_id")
                if not isinstance(entry, dict) or entry.get("id") != pid or pid not in entries or "replacement" not in record:
                    continue
                staged.append((name, record))
            except (OSError, ValueError, TypeError):
                continue
        if not staged:
            return 0
        state = self.state()
        changed, cleared = [], []
        for name, record in staged:
            pid = record["prompt_id"]
            row = self.find(state, pid) or self.history_row(pid)
            if row is None or row[2] != record["replacement"]:
                continue
            if (record["history_after"].get("edited_at") or 0) > (entries[pid].get("edited_at") or 0):
                changed.append({"id": pid, "entry": record["history_after"]})
            cleared.append(name)
        if changed:
            self.commit(changed)
        for name in cleared:
            os.remove(os.path.join(self.directory, name))
        return len(changed)
