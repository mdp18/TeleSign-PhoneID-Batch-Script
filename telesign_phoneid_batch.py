
#!/usr/bin/env python3
import argparse
import base64
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import requests

import threading

def normalize_phone(raw: str) -> str:
    """
    Return digits-only string suitable for TeleSign path parameter.
    Strips spaces, hyphens, parentheses, dots, and leading '+'.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    # Remove UTF-8 BOM if present
    if s.startswith("\ufeff"):
        s = s.lstrip("\ufeff")
    # Drop leading '+' then remove non-digits
    if s.startswith("+"):
        s = s[1:]
    return "".join(ch for ch in s if ch.isdigit())

def looks_like_e164_digits_only(digits: str, min_len: int = 8, max_len: int = 15) -> bool:
    if not digits or not digits.isdigit():
        return False
    n = len(digits)
    return min_len <= n <= max_len


import threading

class RateLimiter:
    """
    Simple global TPS limiter. Ensures at most `tps` requests per second across all threads.
    Uses a monotonic-clock scheduler (no burst allowance).
    """
    def __init__(self, tps: Optional[float] = None):
        self.tps = float(tps) if tps else None
        self._lock = threading.Lock()
        self._next_allowed = 0.0  # monotonic seconds

    def acquire(self):
        if not self.tps or self.tps <= 0:
            return
        interval = 1.0 / self.tps
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next_allowed:
                    self._next_allowed = now + interval
                    return
                sleep_s = self._next_allowed - now
            # Sleep outside lock
            if sleep_s > 0:
                time.sleep(sleep_s)


DEFAULT_BASE_URL = "https://rest-ww.telesign.com"
STANDARD_ENDPOINT_PATH = "/v1/phoneid/{phone}"
LIVE_ENDPOINT_PATH = "/v1/phoneid/live/{phone}"

DEFAULT_ADDONS = ["contact", "number_deactivation", "porting_history"]

def env_or_exit(key: str) -> str:
    val = os.getenv(key)
    if not val:
        sys.stderr.write(f"Missing environment variable: {key}\n")
        sys.exit(2)
    return val

def parse_addons(addons_arg: Optional[str], addons_file: Optional[str]) -> List[str]:
    addons: List[str] = []
    if addons_arg:
        addons += [a.strip() for a in addons_arg.replace(";", ",").split(",") if a.strip()]
    if addons_file:
        with open(addons_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                addons += [str(x).strip() for x in data if str(x).strip()]
            elif isinstance(data, dict) and "addons" in data and isinstance(data["addons"], list):
                addons += [str(x).strip() for x in data["addons"] if str(x).strip()]
            else:
                raise ValueError("addons-file must be a JSON array or an object with an 'addons' array")
    # dedupe preserving order
    seen = set()
    result = []
    for a in addons:
        if a not in seen:
            result.append(a)
            seen.add(a)
    return result


def read_numbers(path: Path, min_digits: int, max_digits: int, skip_invalid: bool = True) -> List[str]:
    numbers: List[str] = []
    is_csv = path.suffix.lower() == ".csv"
    open_kwargs = {"encoding": "utf-8-sig"}  # handle UTF-8 BOM

    if is_csv:
        with open(path, newline="", **open_kwargs) as f:
            reader = csv.reader(f)
            first = True
            for row in reader:
                if not row:
                    continue
                cell = str(row[0]).strip()
                if first:
                    lower = cell.lower()
                    # Auto-detect header row: contains letters or the word 'phone'
                    if any(c.isalpha() for c in lower) or "phone" in lower:
                        first = False
                        continue
                    first = False
                digits = normalize_phone(cell)
                if not digits:
                    continue
                if looks_like_e164_digits_only(digits, min_digits, max_digits):
                    numbers.append(digits)
                elif skip_invalid:
                    print(f"Skipping invalid phone number: {cell}", file=sys.stderr)
                else:
                    numbers.append(digits)
    else:
        with open(path, "r", **open_kwargs) as f:
            for line in f:
                cell = line.strip()
                if not cell:
                    continue
                digits = normalize_phone(cell)
                if not digits:
                    continue
                if looks_like_e164_digits_only(digits, min_digits, max_digits):
                    numbers.append(digits)
                elif skip_invalid:
                    print(f"Skipping invalid phone number: {cell}", file=sys.stderr)
                else:
                    numbers.append(digits)
    return numbers

def build_auth_header(customer_id: str, api_key: str) -> str:
    token = f"{customer_id}:{api_key}".encode("utf-8")
    b64 = base64.b64encode(token).decode("ascii")
    return f"Basic {b64}"

def standard_body(addons_list: List[str], ucid: Optional[str], include_defaults: bool) -> Dict[str, Any]:
    # Merge defaults + custom; build object {addon_name: {}}
    merged = []
    if include_defaults:
        merged.extend(DEFAULT_ADDONS)
    merged.extend(addons_list)
    # dedupe preserve order
    seen = set()
    final = []
    for a in merged:
        if a not in seen:
            final.append(a)
            seen.add(a)
    addons_obj = {a: {} for a in final}
    body: Dict[str, Any] = {"addons": addons_obj}
    if ucid:
        body["ucid"] = ucid
    return body

def call_phoneid_standard(
    session: requests.Session,
    limiter: RateLimiter,
    base_url: str,
    phone: str,
    addons_list: List[str],
    ucid: Optional[str],
    include_defaults: bool,
    timeout: float,
    max_retries: int,
    backoff_factor: float,
) -> Dict[str, Any]:
    url = base_url.rstrip("/") + STANDARD_ENDPOINT_PATH.format(phone=phone)
    payload = standard_body(addons_list, ucid, include_defaults)
    for attempt in range(max_retries + 1):
        try:
            limiter.acquire()
            resp = session.post(url, json=payload, timeout=timeout)
            if resp.status_code in (429,) or (500 <= resp.status_code < 600):
                if attempt < max_retries:
                    time.sleep(backoff_factor * (2 ** attempt))
                    continue
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text}
            return {"phone": phone, "status_code": resp.status_code, "response": data}
        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(backoff_factor * (2 ** attempt))
                continue
            return {"phone": phone, "status_code": -1, "response": {"error": str(e)}}
    return {"phone": phone, "status_code": -1, "response": {"error": "Unexpected control flow"}}

def call_phoneid_live(
    session: requests.Session,
    limiter: RateLimiter,
    base_url: str,
    phone: str,
    ucid: Optional[str],
    timeout: float,
    max_retries: int,
    backoff_factor: float,
) -> Dict[str, Any]:
    url = base_url.rstrip("/") + LIVE_ENDPOINT_PATH.format(phone=phone)
    params = {}
    if ucid:
        params["ucid"] = ucid
    for attempt in range(max_retries + 1):
        try:
            limiter.acquire()
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code in (429,) or (500 <= resp.status_code < 600):
                if attempt < max_retries:
                    time.sleep(backoff_factor * (2 ** attempt))
                    continue
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text}
            return {"phone": phone, "status_code": resp.status_code, "response": data}
        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(backoff_factor * (2 ** attempt))
                continue
            return {"phone": phone, "status_code": -1, "response": {"error": str(e)}}
    return {"phone": phone, "status_code": -1, "response": {"error": "Unexpected control flow"}}

def write_results(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = ["phone", "status_code", "status_description", "json"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            resp = r.get("response", {})
            status_description = None
            if isinstance(resp, dict):
                status = resp.get("status") or {}
                if isinstance(status, dict):
                    status_description = status.get("description")
            writer.writerow({
                "phone": r.get("phone"),
                "status_code": r.get("status_code"),
                "status_description": status_description,
                "json": json.dumps(resp, ensure_ascii=False),
            })

def main():
    parser = argparse.ArgumentParser(description="Batch-call TeleSign PhoneID (standard/live).")
    parser.add_argument("input", type=str, help="Path to CSV or TXT with one phone number per line (CSV uses first column).")
    parser.add_argument("--product", choices=["standard", "live"], default="standard", help="PhoneID product: standard (POST) or live (GET).")
    parser.add_argument("--addons", type=str, default="", help="Custom add-ons (comma/semicolon-separated). Standard only.")
    parser.add_argument("--addons-file", type=str, help="JSON file of add-ons (array or {'addons': [...]}). Standard only.")
    parser.add_argument("--no-default-addons", action="store_true", help="Do NOT include default addons (contact, number_deactivation, porting_history). Standard only.")
    parser.add_argument("--ucid", type=str, help="Optional UCID/use case code, e.g. 'BACF'")
    parser.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL, help=f"Base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout seconds (default: 15)")
    parser.add_argument("--concurrency", type=int, default=5, help="Parallel workers (default: 5)")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries on 429/5xx (default: 3)")
    parser.add_argument("--backoff", type=float, default=1.0, help="Exponential backoff base seconds (default: 1.0)")
    parser.add_argument("--tps-limit", type=float, help="Max requests per second across all threads (e.g., 5).")
    parser.add_argument("--out", type=str, default="phoneid_results.csv", help="Output CSV (default: phoneid_results.csv)")
    parser.add_argument("--proxy", type=str, help="HTTPS proxy URL if needed")
    parser.add_argument("--min-digits", type=int, default=8, help="Minimum digits for a valid phone (default: 8)")
    parser.add_argument("--max-digits", type=int, default=15, help="Maximum digits for a valid phone (default: 15)")
    parser.add_argument("--no-skip-invalid", action="store_true", help="Do not skip invalid rows; send as-is after normalization")
    args = parser.parse_args()

    # Auth
    customer_id = env_or_exit("TELE_SIGN_CUSTOMER_ID")
    api_key = env_or_exit("TELE_SIGN_API_KEY")

    in_path = Path(args.input)
    if not in_path.exists():
        sys.stderr.write(f"Input file not found: {in_path}\n")
        sys.exit(2)

    numbers = read_numbers(in_path, args.min_digits, args.max_digits, skip_invalid=(not args.no_skip_invalid))
    if not numbers:
        sys.stderr.write("No phone numbers parsed from input.\n")
        sys.exit(2)

    # Session + headers
    limiter = RateLimiter(args.tps_limit)

    session = requests.Session()
    session.headers.update({
        "Authorization": build_auth_header(customer_id, api_key),
        "Accept": "application/json",
        "User-Agent": "telesign-phoneid-batch/1.1",
    })
    if args.product == "standard":
        session.headers.update({"Content-Type": "application/json"})
    if args.proxy:
        session.proxies.update({"https": args.proxy, "http": args.proxy})

    addons_list: List[str] = []
    include_defaults = not args.no_default_addons
    if args.product == "standard":
        addons_list = parse_addons(args.addons, args.addons_file)

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        futures = {}
        for phone in numbers:
            if args.product == "standard":
                futures[executor.submit(
                    call_phoneid_standard,
                    session,
                    limiter,
                    args.base_url,
                    phone,
                    addons_list,
                    args.ucid,
                    include_defaults,
                    args.timeout,
                    args.max_retries,
                    args.backoff,
                )] = phone
            else:  # live
                futures[executor.submit(
                    call_phoneid_live,
                    session,
                    limiter,
                    args.base_url,
                    phone,
                    args.ucid,
                    args.timeout,
                    args.max_retries,
                    args.backoff,
                )] = phone

        for fut in as_completed(futures):
            results.append(fut.result())

    out_path = Path(args.out)
    write_results(out_path, results)
    print(f"Wrote {len(results)} results to: {out_path.resolve()}")

if __name__ == "__main__":
    main()
