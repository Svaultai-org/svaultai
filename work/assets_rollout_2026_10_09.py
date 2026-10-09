"""Host-only, scoped reversible rollout. Never print secrets or user records.

Run explicit phases only after the candidate/native release gates pass. The
schema stage contains NO customer data. The private backup remains on the same
server. Production changes are additive migrations, the feature flags below,
and replacement of the existing application container; unrelated settings stay.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["prepare", "stage-schema", "migrate", "candidate", "promote", "verify", "cleanup"])
parser.add_argument("commit")
args = parser.parse_args()
assert re.fullmatch(r"[a-f0-9]{40}", args.commit)
short = args.commit[:12]
root = Path("/opt/svaultai")
source = root / ("assets-source-" + short)
image = "svaultai-backend:assets-" + short
runtime = root / ("runtime-assets-" + short + ".env")
rollback_runtime = root / ("runtime-assets-rollback-" + short + ".env")
stage_runtime = root / ("runtime-assets-stage-" + short + ".env")
rollback_stage_runtime = root / ("runtime-assets-rollback-stage-" + short + ".env")
state_path = root / ("assets-" + short + ".json")
candidate = "svaultai-assets-candidate-" + short
rollback_candidate = "svaultai-assets-rollback-check-" + short
retired = "vaultai-backend-pre-assets-" + short
stage_db = "svaultai_assets_stage_" + short
db_container = "svaultai-production-postgres-new"
updates = {
    "VAULTAI_ASSETS_PAXG_ENABLED": "true",
    "VAULTAI_ASSETS_KAG_ENABLED": "true",
    "VAULTAI_CONCIERGE_ENABLED": "true",
    "VAULTAI_CONCIERGE_PROVIDER_MODE": "free",
    "VAULTAI_CONCIERGE_BACKGROUND_ENABLED": "false",
    "VAULTAI_CONCIERGE_STEALER_LOGS_ENABLED": "false",
}

def safe_error():
    # Provider/SQL/Docker failures may include credentials, addresses or keys.
    raise RuntimeError("Scoped phase failed; production switch not approved. Inspect private host diagnostics without sharing secret values.")

def run(command, *, binary=False, input_data=None):
    result = subprocess.run(command, input=input_data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=not binary)
    if result.returncode:
        safe_error()
    return result.stdout if binary else result.stdout.strip()

def inspect(name):
    return json.loads(run(["docker", "inspect", name]))[0]

def private_file(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(value.encode() if isinstance(value, str) else value)

def env_file(path, env):
    assert all("\n" not in k + v for k, v in env.items())
    private_file(path, "\n".join(k + "=" + v for k, v in env.items()) + "\n")

def load_env():
    return dict(line.split("=", 1) for line in runtime.read_text().splitlines())

def execute_python(container, code):
    return run(["docker", "exec", container, "python", "-c", code])

def health(port):
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=2) as response:
                value = json.load(response)
            if value == {"status": "ok", "db": "connected"} or (
                value.get("status") == "ok" and value.get("db") == "connected"):
                return
        except Exception:
            pass
        time.sleep(.5)
    safe_error()

def check(container, port):
    health(port)
    with urllib.request.urlopen("http://127.0.0.1:%d/openapi.json" % port, timeout=5) as response:
        paths = json.load(response)["paths"]
    for path in ["/crypto/wallet/asset-catalog", "/concierge/capabilities", "/concierge/state",
                 "/billing/apple/verify-transaction", "/billing/apple/transactions", "/billing/google-play/verify"]:
        assert path in paths
    assert not any("stripe" in p or "checkout-session" in p for p in paths)
    code = "import json; from verified_assets import build_asset_catalog; print(json.dumps(build_asset_catalog()))"
    catalog = json.loads(execute_python(container, code))
    categories = {x["id"]: x for x in catalog["categories"]}
    for name in ("digital_gold", "digital_silver"):
        assert categories[name]["available"], categories[name].get("reason")
    for item in catalog["assets"]:
        assert all(item.get(key) is True for key in ("verified", "receiveEnabled", "balanceEnabled", "sendEnabled", "activityConnected"))
    for name, item in categories.items():
        if name not in ("cryptocurrency", "digital_gold", "digital_silver"):
            assert item["available"] is False
    billing = json.loads(execute_python(container, "import json,runpy; runpy.run_path('scripts/verify_apple_billing.py', run_name='__main__')"))
    assert billing["apple_billing_ready"] and billing["required_products"] == 17
    exposure = json.loads(execute_python(container, "import json; from concierge_exposure import capabilities; print(json.dumps(capabilities()))"))
    assert exposure["enabled"] is True and exposure["provider_mode"] == "free"
    # Auth refusal proves the new public surface is not an anonymous vault leak.
    import urllib.error
    for path in ("/crypto/wallet/asset-catalog", "/concierge/state"):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5)
            safe_error()
        except urllib.error.HTTPError as error:
            assert error.code in (401, 403)
    return {"health": "ok", "db": "connected", "gold_verified": True,
            "silver_verified": True, "unsupported_categories_disabled": True,
            "billing_verifier_ready": True, "anonymous_vault_access_refused": True}

def command(state, name, port, env_path=runtime, *, migration=False, selected_image=None):
    result = ["docker", "run", "--name", name, "--network", state["network"], "--env-file", str(env_path)]
    if not migration:
        result += ["-d", "--restart", state["restart"], "-p", "127.0.0.1:%d:8000" % port]
    else:
        result += ["--rm", "--entrypoint", "python"]
    result += ["--user", state["user"], "--workdir", state["working_dir"], "--log-driver", state["log"]["Type"]]
    for key, value in state["log"]["Config"].items():
        result += ["--log-opt", key + "=" + value]
    for value in state["security_options"]:
        result += ["--security-opt", value]
    for value in state["cap_add"]:
        result += ["--cap-add", value]
    for value in state["cap_drop"]:
        result += ["--cap-drop", value]
    if state["read_only_root"]:
        result += ["--read-only"]
    for mount in state["mounts"]:
        assert mount["Type"] == "bind" and not mount["RW"]
        result += ["--mount", "type=bind,source=%s,target=%s,readonly" % (mount["Source"], mount["Destination"])]
    return result + [selected_image or image] + (["-m", "alembic", "upgrade", "head"] if migration else state["cmd"])

def exists(name):
    return subprocess.run(["docker", "container", "inspect", name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0

def verify_settings(name, state):
    actual = inspect(name)
    host = actual["HostConfig"]
    assert actual["Config"]["User"] == state["user"]
    assert actual["Config"]["WorkingDir"] == state["working_dir"]
    assert host["SecurityOpt"] == (state["security_options"] or None)
    assert host["LogConfig"] == state["log"]
    assert host["ReadonlyRootfs"] == state["read_only_root"]
    assert host["CapAdd"] == (state["cap_add"] or None)
    assert host["CapDrop"] == (state["cap_drop"] or None)
    assert host["RestartPolicy"] == state["restart_policy"]
    assert actual["Mounts"] == state["mounts"]

if args.phase == "prepare":
    old = inspect("vaultai-backend")
    assert old["State"]["Running"] and old["Config"]["Image"] == "svaultai-backend:apple-billing-f801c25"
    new = inspect(image)
    assert new["Config"]["Labels"]["org.opencontainers.image.revision"] == args.commit
    assert list(old["NetworkSettings"]["Networks"]) == ["svaultai-production-v2-net"]
    host = old["HostConfig"]
    assert host["PortBindings"] == {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}
    assert not host["Privileged"] and old["Config"]["Entrypoint"] is None
    assert not exists(retired) and not exists(candidate) and not exists(rollback_candidate)
    # Fail closed for safety/resource settings this narrowly scoped clone does
    # not yet translate, rather than silently losing them at replacement.
    assert host.get("Memory", 0) == 0 and host.get("NanoCpus", 0) == 0
    assert host.get("PidsLimit") is None and host.get("Ulimits") == []
    assert not host.get("UsernsMode") and old.get("AppArmorProfile") == "docker-default"
    for key in ("User", "WorkingDir"):
        assert old["Config"][key] == new["Config"][key]
    assert (source / "requirements.txt").read_bytes() == (root / "apple-billing-source-f801c25/requirements.txt").read_bytes()
    env = dict(line.split("=", 1) for line in old["Config"]["Env"])
    assert not any(k.startswith("STRIPE_") for k in env)
    old_env = dict(env)
    # Retain the immutable old code with compatible startup against the new
    # additive schema. It cannot discover future Alembic revisions itself.
    rollback_env = dict(old_env)
    rollback_env["RUN_MIGRATIONS_ON_STARTUP"] = "false"
    env_file(rollback_runtime, rollback_env)
    env.update(updates)
    assert all(env.get(k) == v for k, v in old_env.items() if k not in updates)
    env_file(runtime, env)
    db = urlsplit(env["DATABASE_URL"])
    assert db.path and re.fullmatch(r"/[a-zA-Z0-9_]+", db.path)
    db_env = dict(x.split("=", 1) for x in inspect(db_container)["Config"]["Env"])
    db_user = db_env.get("POSTGRES_USER", "postgres")
    assert re.fullmatch(r"[a-zA-Z0-9_]+", db_user)
    restart = dict(host["RestartPolicy"])
    restart_arg = restart["Name"]
    if restart["Name"] == "on-failure" and restart["MaximumRetryCount"]:
        restart_arg += ":" + str(restart["MaximumRetryCount"])
    state = {"old_id": old["Id"], "old_image": old["Image"],
             "cmd": old["Config"]["Cmd"], "restart": restart_arg,
             "restart_policy": restart, "log": host["LogConfig"],
             "user": old["Config"]["User"], "working_dir": old["Config"]["WorkingDir"],
             "security_options": host["SecurityOpt"] or [], "cap_add": host["CapAdd"] or [],
             "cap_drop": host["CapDrop"] or [], "read_only_root": host["ReadonlyRootfs"],
             "mounts": old["Mounts"], "network": "svaultai-production-v2-net",
             "db_name": db.path[1:], "db_user": db_user, "stage_db": stage_db}
    private_file(state_path, json.dumps(state))
    print("Preserved production configuration; only scoped feature flags prepared")
else:
    state = json.loads(state_path.read_text())
    assert state["stage_db"] == stage_db
    if args.phase == "stage-schema":
        schema = run(["docker", "exec", db_container, "pg_dump", "-U", state["db_user"],
                      "-d", state["db_name"], "--schema-only", "--no-owner", "--no-privileges"], binary=True)
        run(["docker", "exec", db_container, "createdb", "-U", state["db_user"], stage_db])
        run(["docker", "exec", "-i", db_container, "psql", "-v", "ON_ERROR_STOP=1", "-U", state["db_user"], "-d", stage_db],
            binary=True, input_data=schema)
        run(["docker", "exec", db_container, "psql", "-v", "ON_ERROR_STOP=1", "-U", state["db_user"], "-d", stage_db,
             "-c", "INSERT INTO alembic_version(version_num) VALUES ('0046_store_only_billing')"])
        stage_env = load_env()
        parts = urlsplit(stage_env["DATABASE_URL"])
        stage_env["DATABASE_URL"] = urlunsplit((parts.scheme, parts.netloc, "/" + stage_db, parts.query, parts.fragment))
        env_file(stage_runtime, stage_env)
        run(command(state, "svaultai-assets-migrate-stage-" + short, 0, stage_runtime, migration=True))
        head = run(["docker", "exec", db_container, "psql", "-U", state["db_user"], "-d", stage_db, "-Atc", "SELECT version_num FROM alembic_version"])
        assert head == "0049_kag_encrypted_draft_binding"
        rollback_env = dict(line.split("=", 1) for line in rollback_runtime.read_text().splitlines())
        parts = urlsplit(rollback_env["DATABASE_URL"])
        rollback_env["DATABASE_URL"] = urlunsplit((parts.scheme, parts.netloc, "/" + stage_db, parts.query, parts.fragment))
        env_file(rollback_stage_runtime, rollback_env)
        run(command(state, rollback_candidate, 18002, rollback_stage_runtime, selected_image=state["old_image"]))
        verify_settings(rollback_candidate, state)
        health(18002)
        billing = json.loads(execute_python(rollback_candidate, "import json,runpy; runpy.run_path('scripts/verify_apple_billing.py', run_name='__main__')"))
        assert billing["apple_billing_ready"] and billing["required_products"] == 17
        state["rollback_stage_passed"] = True
        state_path.write_text(json.dumps(state))
        print("Production-shaped empty schema migrated successfully; no customer data copied")
    elif args.phase == "migrate":
        assert state.get("rollback_stage_passed")
        head = run(["docker", "exec", db_container, "psql", "-U", state["db_user"], "-d", state["db_name"], "-Atc", "SELECT version_num FROM alembic_version"])
        assert head == "0046_store_only_billing"
        assert run(["docker", "exec", db_container, "psql", "-U", state["db_user"], "-d", stage_db, "-Atc", "SELECT version_num FROM alembic_version"]) == "0049_kag_encrypted_draft_binding"
        backup = root / "backups" / ("pre-assets-" + short + ".dump")
        dump = run(["docker", "exec", db_container, "pg_dump", "-U", state["db_user"], "-d", state["db_name"], "-Fc", "--no-owner", "--no-privileges"], binary=True)
        assert len(dump) > 1000
        private_file(backup, dump)
        run(command(state, "svaultai-assets-migrate-live-" + short, 0, migration=True))
        print("Private host backup retained; additive feature migrations applied")
    elif args.phase == "candidate":
        # Startup workers can reconcile records: the staging candidate must
        # NEVER point them at customer data. Catalog checks need no live rows.
        run(command(state, candidate, 18001, stage_runtime))
        verify_settings(candidate, state)
        print(json.dumps(check(candidate, 18001), sort_keys=True))
    elif args.phase == "promote":
        check(candidate, 18001)
        assert state.get("rollback_stage_passed") and not exists(retired)
        assert inspect("vaultai-backend")["Id"] == state["old_id"]
        try:
            run(["docker", "stop", "--time", "30", "vaultai-backend"])
            run(["docker", "rename", "vaultai-backend", retired])
            run(command(state, "vaultai-backend", 8000))
            verify_settings("vaultai-backend", state)
            result = check("vaultai-backend", 8000)
        except Exception:
            # Preserve the intact original for forensic recovery. Recreate its
            # proven old-code runtime with startup migrations disabled so the
            # schema remains forward-compatible; NEVER downgrade live data.
            if exists("vaultai-backend"):
                remaining = inspect("vaultai-backend")
                if remaining["Id"] == state["old_id"] and remaining["State"]["Running"]:
                    # A failed stop must not rename a still-serving original
                    # or create another process competing for its live port.
                    health(8000)
                    raise
                if remaining["Id"] == state["old_id"]:
                    run(["docker", "rename", "vaultai-backend", retired])
                else:
                    assert remaining["Config"]["Image"] == image
                    assert remaining["Config"]["Labels"]["org.opencontainers.image.revision"] == args.commit
                    run(["docker", "rm", "-f", "vaultai-backend"])
            run(command(state, "vaultai-backend", 8000, rollback_runtime, selected_image=state["old_image"]))
            verify_settings("vaultai-backend", state)
            health(8000)
            raise
        print(json.dumps({"production_assets_deployed": True, "rollback_retained": True, **result}, sort_keys=True))
    elif args.phase == "verify":
        assert inspect("vaultai-backend")["Config"]["Image"] == image
        print(json.dumps(check("vaultai-backend", 8000), sort_keys=True))
    elif args.phase == "cleanup":
        assert inspect("vaultai-backend")["Config"]["Image"] == image
        assert inspect(candidate)["Config"]["Image"] == image
        run(["docker", "rm", "-f", candidate])
        assert inspect(rollback_candidate)["Image"] == state["old_image"]
        run(["docker", "rm", "-f", rollback_candidate])
        assert stage_db.startswith("svaultai_assets_stage_") and stage_db != state["db_name"]
        run(["docker", "exec", db_container, "dropdb", "-U", state["db_user"], stage_db])
        print("Temporary candidate and empty staging database removed; original container and private backup retained")
