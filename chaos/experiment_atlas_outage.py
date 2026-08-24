#!/usr/bin/env python3
"""Chaos experiment: does a plan still return flights when its data sources die?

Hypothesis (steady state): a flights search returns >= 1 flight AND completes
(status=done) even when Atlas — and then Camofox too — is fully down. This
proves the Atlas -> Amadeus -> Camofox -> LLM/mock fallback ladder.

Attack: dependency-failure, injected via the dev-gated /chaos endpoints.
Blast radius: a single in-memory flag on a non-prod stack (GREEN).
Abort / rollback: /chaos/clear (always run, even on failure).

Usage: python chaos/experiment_atlas_outage.py [API_BASE]
"""

import json
import sys
import time
import urllib.request as U

API = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8401") + "/api/v1"
CREDS = {"email": "admin@journava.test", "password": "Journava!2026"}


def call(method, path, body=None, tok=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = U.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    with U.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or "{}")


def run_flights(tok, dest):
    jid = call("POST", "/jobs/plan", {
        "goal": f"flights KLIA to {dest}", "scope": "flights_only",
        "destination": dest, "origin": "KLIA", "start_date": "2026-11-15",
    }, tok)["id"]
    for _ in range(90):
        job = call("GET", f"/jobs/{jid}", tok=tok)
        if job.get("status") in ("done", "error"):
            break
        time.sleep(2)
    res = (job.get("result") or {}).get("results") or {}
    fl = (res.get("flight") or {}).get("options") or []
    by_atlas = sum(1 for o in fl if o.get("source") == "atlas")
    return {"status": job.get("status"), "flights": len(fl), "atlas": by_atlas,
            "sources": sorted({o.get("source") for o in fl})}


def check(name, cond, detail):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} — {detail}")
    return cond


def main():
    tok = call("POST", "/auth/login", CREDS)["access_token"]
    st = call("GET", "/chaos/status", tok=tok)
    print("Chaos status:", st)
    if not st.get("enabled"):
        print("Chaos disabled in this environment — aborting (this is the prod safeguard).")
        return
    results = []
    try:
        print("\n[1] Steady state (all systems up) — KLIA->Tokyo")
        call("POST", "/chaos/clear", tok=tok)
        base = run_flights(tok, "Tokyo")
        print("   ", base)
        results.append(check("baseline returns flights", base["status"] == "done" and base["flights"] > 0, f"{base['flights']} flights"))

        print("\n[2] Attack: Atlas outage — KLIA->Osaka")
        call("POST", "/chaos/inject", {"target": "atlas", "action": "down"}, tok)
        a1 = run_flights(tok, "Osaka")
        print("   ", a1)
        results.append(check("plan survives Atlas outage", a1["status"] == "done" and a1["flights"] > 0, f"{a1['flights']} flights, {a1['atlas']} from Atlas (expect 0), sources={a1['sources']}"))

        print("\n[3] Attack: Atlas + Camofox outage — KLIA->Fukuoka")
        call("POST", "/chaos/inject", {"target": "camofox", "action": "down"}, tok)
        a2 = run_flights(tok, "Fukuoka")
        print("   ", a2)
        results.append(check("plan survives BOTH outages (LLM/mock fallback)", a2["status"] == "done" and a2["flights"] > 0, f"{a2['flights']} flights, sources={a2['sources']}"))
    finally:
        print("\n[abort/rollback] clearing all injected faults")
        call("POST", "/chaos/clear", tok=tok)
        print("   ", call("GET", "/chaos/status", tok=tok))

    verdict = "GREEN — steady state held under failure" if all(results) else "RED — steady state broke"
    print(f"\n=== RESULT: {verdict} ({sum(results)}/{len(results)} checks passed) ===")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
