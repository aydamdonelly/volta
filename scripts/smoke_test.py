"""Connectivity smoke test for Volta — verifies every external service the
locked plan depends on actually works with the credentials in .env.local.

Read-only w.r.t. .env.local. Anthropic test uses one tiny Haiku call (budget).
Run: .venv/bin/python scripts/smoke_test.py
"""
from __future__ import annotations

import os
import sys
import traceback

from dotenv import load_dotenv

load_dotenv(".env.local")

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def test_anthropic() -> None:
    try:
        import anthropic

        key = os.environ["ANTHROPIC_API_KEY"]
        client = anthropic.Anthropic(api_key=key)
        # Cheapest possible validity probe: Haiku, 5 tokens.
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with: ok"}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        record(
            "Anthropic",
            True,
            f"model=claude-haiku-4-5 reply={text!r} "
            f"in_tok={msg.usage.input_tokens} out_tok={msg.usage.output_tokens}",
        )
    except Exception as e:  # noqa: BLE001
        record("Anthropic", False, f"{type(e).__name__}: {e}")


def test_volue_insight() -> None:
    try:
        import pandas as pd
        import volue_insight_timeseries as vit

        session = vit.Session(
            urlbase=os.environ.get("VOLUE_INSIGHT_API_URL"),
            auth_urlbase=os.environ.get("VOLUE_INSIGHT_AUTH_URL"),
            client_id=os.environ["VOLUE_INSIGHT_CLIENT_ID"],
            client_secret=os.environ["VOLUE_INSIGHT_CLIENT_SECRET"],
            timeout=300,
        )
        target = "pri de spot €/mwh cet h a"
        curve = None
        found_via = None
        try:
            hits = session.search(name=target)
            if hits:
                curve = hits[0]
                found_via = f"search -> {len(hits)} hit(s)"
        except Exception:  # noqa: BLE001
            pass
        if curve is None:
            curve = session.get_curve(name=target)
            found_via = "get_curve (direct)"
        if curve is None:
            record("Volue Insight", False, f"auth ok but curve {target!r} not found")
            return

        name = getattr(curve, "name", target)
        ctype = getattr(curve, "curve_type", "?")
        ts = curve.get_data(
            data_from=pd.Timestamp("2026-01-01 00:00"),
            data_to=pd.Timestamp("2026-01-03 00:00"),  # end exclusive
        )
        s = ts.to_pandas()
        record(
            "Volue Insight",
            len(s) > 0,
            f"{found_via}; curve={name!r} type={ctype}; "
            f"2026-01-01..02 rows={len(s)} "
            f"min={s.min():.2f} max={s.max():.2f} first={s.iloc[0]:.2f}",
        )
    except Exception as e:  # noqa: BLE001
        record("Volue Insight", False, f"{type(e).__name__}: {e}")


def test_optimeering() -> None:
    try:
        from optimeering_beta import Configuration, OptimeeringClient

        key = os.environ["OPTIMEERING_API_KEY"]
        host = os.environ.get("OPTIMEERING_HOST")
        try:
            cfg = Configuration(host=host, api_key=key)
        except TypeError:
            cfg = Configuration(api_key=key)
        client = OptimeeringClient(cfg)
        # list_series() (no filter) is a documented metadata call,
        # properly typed -> real authenticated round trip.
        series = client.predictions_api.list_series()
        items = getattr(series, "items", None) or []
        n = len(items)
        sample = ""
        if items:
            f = items[0]
            sample = (
                f" e.g. id={getattr(f,'id','?')} area={getattr(f,'area','?')} "
                f"product={getattr(f,'product','?')} stat={getattr(f,'statistic','?')}"
            )
        record(
            "Optimeering",
            n > 0,
            f"host={host} list_series -> {n} series{sample}",
        )
    except Exception as e:  # noqa: BLE001
        record("Optimeering", False, f"{type(e).__name__}: {e}")


def test_netztransparenz() -> None:
    try:
        import requests

        token_url = os.environ["NETZTRANSPARENZ_TOKEN_URL"]
        cid = os.environ["NETZTRANSPARENZ_CLIENT_ID"]
        secret = os.environ["NETZTRANSPARENZ_CLIENT_SECRET"]
        r = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": secret,
            },
            timeout=30,
        )
        if r.status_code != 200:
            record(
                "Netztransparenz",
                False,
                f"token endpoint HTTP {r.status_code}: {r.text[:200]}",
            )
            return
        tok = r.json().get("access_token")
        if not tok:
            record("Netztransparenz", False, f"no access_token in response: {r.text[:200]}")
            return
        # Bonus: authenticated GET against the data service.
        api = "https://ds.netztransparenz.de/api/v1/health/ping"
        g = requests.get(api, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        record(
            "Netztransparenz",
            True,
            f"token issued (len={len(tok)}); GET {api} -> HTTP {g.status_code}",
        )
    except Exception as e:  # noqa: BLE001
        record("Netztransparenz", False, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    print("=== Volta connectivity smoke test ===", flush=True)
    for fn in (test_anthropic, test_volue_insight, test_optimeering, test_netztransparenz):
        try:
            fn()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            record(fn.__name__, False, "uncaught exception")
    print("\n=== SUMMARY ===", flush=True)
    failed = [n for n, ok, _ in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    if failed:
        print(f"\n{len(failed)} FAILED: {', '.join(failed)}", flush=True)
        sys.exit(1)
    print("\nALL PASSED", flush=True)
