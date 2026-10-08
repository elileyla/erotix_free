#!/usr/bin/env python3
"""Respectfully check VLESS+REALITY links and publish a healthy subscription.

The source list is deliberately static: IPSpeed does not expose a documented
machine-readable export in the page we inspected. This script checks the links
in config/source.txt; it does not scrape IPSpeed or add newly published nodes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DEFAULT_PROBES = (
    "https://www.cloudflare.com/cdn-cgi/trace",
    "https://www.gstatic.com/generate_204",
)
SUPPORTED_METHODS = {"raw", "tcp", "grpc", "xhttp"}
PROXY_ENV_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
)


def first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def parse_vless(link: str) -> dict:
    link = link.strip()
    try:
        uri = urlsplit(link)
        port = uri.port
    except ValueError as exc:
        raise ValueError(f"malformed VLESS URI: {exc}") from exc

    if uri.scheme.lower() != "vless":
        raise ValueError("scheme must be vless://")
    if not uri.username or not uri.hostname or port is None or not (1 <= port <= 65535):
        raise ValueError("missing or invalid UUID, server, or port")

    query = parse_qs(uri.query, keep_blank_values=True)
    if first(query, "security").lower() != "reality":
        raise ValueError("only security=reality entries are checked")
    if not first(query, "pbk"):
        raise ValueError("missing Reality public key (pbk)")
    if not first(query, "sni"):
        raise ValueError("missing server name (sni)")

    method = (first(query, "type", "raw") or "raw").lower()
    if method not in SUPPORTED_METHODS:
        raise ValueError(f"unsupported Reality transport type: {method}")
    if method == "tcp":
        method = "raw"  # Xray's current transport name; tcp is an old alias.

    short_id = first(query, "sid")
    if short_id and (len(short_id) > 16 or len(short_id) % 2 or any(c not in "0123456789abcdefABCDEF" for c in short_id)):
        raise ValueError("sid must be an even-length hexadecimal string of at most 16 characters")

    return {
        "link": link,
        "uuid": uri.username,
        "server": uri.hostname,
        "port": port,
        "query": query,
        "method": method,
    }


def build_xray_config(item: dict, socks_port: int) -> dict:
    query = item["query"]
    user = {
        "id": item["uuid"],
        "encryption": "none",
    }
    flow = first(query, "flow")
    if flow:
        user["flow"] = flow

    reality = {
        "serverName": first(query, "sni"),
        "fingerprint": first(query, "fp") or "chrome",
        # In current Xray JSON this client-side field is called "password".
        # It is the public key carried by pbk in the VLESS URI.
        "password": first(query, "pbk"),
        "shortId": first(query, "sid"),
    }
    spider_x = first(query, "spx")
    if spider_x:
        reality["spiderX"] = spider_x

    stream = {
        "method": item["method"],
        "security": "reality",
        "realitySettings": reality,
    }

    if item["method"] == "grpc":
        grpc = {}
        service_name = first(query, "serviceName")
        authority = first(query, "authority")
        if service_name:
            grpc["serviceName"] = service_name
        if authority:
            grpc["authority"] = authority
        stream["grpcSettings"] = grpc
    elif item["method"] == "xhttp":
        xhttp = {"mode": first(query, "mode") or "auto"}
        host = first(query, "host")
        path = first(query, "path")
        if host:
            xhttp["host"] = host
        if path:
            xhttp["path"] = path
        stream["xhttpSettings"] = xhttp

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": False},
            }
        ],
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {
                    "address": item["server"],
                    "port": item["port"],
                    "id": user["id"],
                    "encryption": user["encryption"],
                    **({"flow": user["flow"]} if "flow" in user else {}),
                },
                "streamSettings": stream,
            }
        ],
    }


def validate_with_xray(xray: str, item: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="vless-validate-") as tmp:
        config_path = Path(tmp) / "config.json"
        config_path.write_text(json.dumps(build_xray_config(item, 18080)), encoding="utf-8")
        try:
            result = subprocess.run(
                [xray, "run", "-test", "-c", str(config_path)],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"Xray config test failed: {exc}"
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "Xray rejected the config").strip()
            return False, message[-600:]
    return True, "config OK"


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_socks(port: int, process: subprocess.Popen, seconds: float = 4.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def curl_probe(port: int, url: str, timeout: int) -> tuple[bool, str]:
    proxy = f"socks5h://127.0.0.1:{port}"
    command = [
        "curl", "--silent", "--show-error", "--location",
        "--max-time", str(timeout), "--connect-timeout", "5",
        "--proxy", proxy, "--noproxy", "",
        "--output", "-", "--write-out", "\\n%{http_code}", url,
    ]
    env = os.environ.copy()
    for name in PROXY_ENV_VARS:
        env.pop(name, None)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 3, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"probe error: {exc}"
    if result.returncode != 0:
        message = (result.stderr or f"curl exited {result.returncode}").strip()
        return False, message[-300:]
    output = result.stdout
    try:
        status = int(output.rsplit("\n", 1)[-1].strip())
    except ValueError:
        return False, "probe returned no HTTP status"
    if not (200 <= status < 400):
        return False, f"probe HTTP status {status}"
    return True, f"HTTP {status} via proxy"


def check_one(xray: str, link: str, probe_urls: tuple[str, ...], timeout: int) -> tuple[str, bool, str]:
    try:
        item = parse_vless(link)
    except Exception as exc:
        return link, False, f"invalid: {exc}"

    valid, message = validate_with_xray(xray, item)
    if not valid:
        return link, False, f"invalid Xray config: {message}"

    port = reserve_local_port()
    with tempfile.TemporaryDirectory(prefix="vless-probe-") as tmp:
        config_path = Path(tmp) / "config.json"
        log_path = Path(tmp) / "xray.log"
        config_path.write_text(json.dumps(build_xray_config(item, port)), encoding="utf-8")
        with log_path.open("w+", encoding="utf-8") as log_file:
            try:
                process = subprocess.Popen(
                    [xray, "run", "-c", str(config_path)],
                    cwd=tmp,
                    stdout=log_file,
                    stderr=log_file,
                    start_new_session=True,
                )
            except OSError as exc:
                return link, False, f"could not start Xray: {exc}"
            try:
                if not wait_for_socks(port, process):
                    log_file.flush()
                    log_file.seek(0)
                    detail = log_file.read()[-400:].strip()
                    return link, False, "local SOCKS inbound did not start" + (f": {detail}" if detail else "")
                errors = []
                for probe_url in probe_urls:
                    ok, detail = curl_probe(port, probe_url, timeout)
                    if ok:
                        return link, True, detail
                    errors.append(f"{probe_url}: {detail}")
                return link, False, "; ".join(errors)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)


def load_source(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"source list not found: {path}")
    links = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            links.append(value)
    return list(dict.fromkeys(links))


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        print(f"Warning: state file {path} is unreadable; starting a fresh failure history.", file=sys.stderr)
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def write_action_summary(summary: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="config/source.txt")
    parser.add_argument("--state", default="state/probe-state.json")
    parser.add_argument("--out-dir", default="dist")
    parser.add_argument("--xray", default=os.environ.get("XRAY_BIN", "xray"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--failures-before-removal", type=int, default=2)
    parser.add_argument("--validate-only", action="store_true", help="validate URI and Xray JSON only; do not contact servers")
    args = parser.parse_args()

    if args.workers < 1 or args.timeout < 1 or args.failures_before_removal < 1:
        parser.error("workers, timeout, and failures-before-removal must be positive")
    xray = str(Path(args.xray).expanduser().resolve())
    if not Path(xray).is_file():
        print(f"Xray binary not found: {xray}", file=sys.stderr)
        return 2

    source_path = Path(args.source)
    links = load_source(source_path)
    if not links:
        print(f"No links found in {source_path}; refusing to run.", file=sys.stderr)
        return 2

    if args.validate_only:
        ok_count = 0
        failures = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {}
            for link in links:
                try:
                    item = parse_vless(link)
                except Exception as exc:
                    failures.append((link, f"invalid URI: {exc}"))
                    continue
                futures[pool.submit(validate_with_xray, xray, item)] = link
            for future in as_completed(futures):
                link = futures[future]
                good, message = future.result()
                if good:
                    ok_count += 1
                else:
                    failures.append((link, message))
        print(f"Offline validation: {ok_count}/{len(links)} Xray configs accepted; no network probes were made.")
        for link, message in failures:
            print(f"FAIL {link[:100]} — {message}")
        return 0 if not failures else 1

    previous_state = load_state(Path(args.state))
    next_state = {}
    probe_urls = DEFAULT_PROBES
    results = []
    invalid_count = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(check_one, xray, link, probe_urls, args.timeout): link for link in links}
        for future in as_completed(futures):
            link = futures[future]
            try:
                checked_link, passed, message = future.result()
            except Exception as exc:
                checked_link, passed, message = link, False, f"unexpected checker error: {exc}"
            results.append((checked_link, passed, message))

    # Preserve source order in output and state processing, independent of worker completion order.
    results_by_link = {line: (passed, message) for line, passed, message in results}
    active = []
    passed_count = grace_count = removed_count = 0
    failed_messages = []
    for link in links:
        passed, message = results_by_link.get(link, (False, "missing checker result"))
        key = hashlib.sha256(link.encode("utf-8")).hexdigest()
        old = previous_state.get(key, {}) if isinstance(previous_state.get(key, {}), dict) else {}
        old_failures = max(0, int(old.get("failures", 0)))
        ever_ok = bool(old.get("ever_ok", False))

        if passed:
            passed_count += 1
            ever_ok = True
            failures = 0
            active.append(link)
            status = "healthy"
        else:
            failures = old_failures + 1
            failed_messages.append((link, message))
            if message.startswith("invalid"):
                invalid_count += 1
            if ever_ok and failures < args.failures_before_removal:
                active.append(link)
                grace_count += 1
                status = "grace"
            else:
                removed_count += 1
                status = "failed"
        next_state[key] = {"failures": failures, "ever_ok": ever_ok, "last_status": status}

    save_state(Path(args.state), next_state)

    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    wrote_outputs = False
    if active:
        plain = "\n".join(active) + "\n"
        encoded = base64.b64encode(plain.encode("utf-8")).decode("ascii") + "\n"
        (output_dir / "active.txt").write_text(plain, encoding="utf-8")
        (output_dir / "active.base64.txt").write_text(encoded, encoding="ascii")
        wrote_outputs = True
    else:
        print("Warning: no link passed health checks or grace rules; keeping any previous dist/ subscription instead of publishing an empty file.", file=sys.stderr)

    report = [
        "## VLESS + REALITY health check",
        f"- Source links: **{len(links)}**",
        f"- Passed this run: **{passed_count}**",
        f"- Kept after one transient failure: **{grace_count}**",
        f"- Excluded after failure / invalid config: **{removed_count}**",
        f"- Invalid links/configs: **{invalid_count}**",
        f"- Subscription outputs refreshed: **{'yes' if wrote_outputs else 'no (kept last known good)'}**",
        "- Probe: Cloudflare trace, then Google connectivity check, through a local Xray SOCKS5 inbound.",
    ]
    write_action_summary("\n".join(report))
    print("\n".join(report))
    for link, message in failed_messages:
        print(f"NOT HEALTHY {link[:100]} — {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
