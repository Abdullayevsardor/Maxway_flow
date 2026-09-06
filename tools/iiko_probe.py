"""iikoCloud API bilan aloqani tekshirish va kerakli ID larni topish.

Ishlatish (loyiha papkasidan):

    python tools/iiko_probe.py                # tashkilotlar + terminal guruhlar + stop-list
    python tools/iiko_probe.py --orgs         # faqat tashkilotlar
    python tools/iiko_probe.py --terminals    # tashkilotlar + terminal guruhlar
    python tools/iiko_probe.py --stops        # stop-list (taom nomlari bilan)
    python tools/iiko_probe.py --raw          # stop-list pozitsiyalarini xom JSON bilan

Kalitlar app/iiko.py dagi bilan bir xil joydan olinadi: MAXWAY_IIKO_LOGIN /
MAXWAY_IIKO_APP_ID / MAXWAY_IIKO_CLIENT_SECRET env yoki iiko_login.txt fayli.

Bu skript FAQAT o'qiydi — iiko'ga hech narsa yozmaydi.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.iiko import IikoClient, IikoError, get_credentials  # noqa: E402

# Windows konsoli cp1251 bo'lishi mumkin — ✓/✗ va ruscha nomlar sinmasin
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def show_orgs(orgs: list):
    print(f"\n=== TASHKILOTLAR ({len(orgs)} ta) ===")
    for o in orgs:
        print(f"  {o.get('id')}   {o.get('name')}")


def show_terminals(groups: dict, orgs: list):
    by_id = {o.get("id"): o.get("name") for o in orgs}
    total = sum(len(v) for v in groups.values())
    print(f"\n=== TERMINAL GURUHLAR ({total} ta) ===")
    print("  Har bir filialga mos terminal guruh ID sini «Админ → Филиалы» da tanlaymiz.")
    for org_id, items in groups.items():
        print(f"\n  Tashkilot: {by_id.get(org_id, org_id)}")
        for t in items:
            addr = t.get("address") or ""
            print(f"    {t.get('id')}   {t.get('name')}{'   — ' + addr if addr else ''}")


def show_stops(stops: dict, groups: dict, names: dict, raw: bool):
    tg_names = {}
    for items in groups.values():
        for t in items:
            tg_names[t.get("id")] = t.get("name")
    total = sum(len(v) for v in stops.values())
    print(f"\n=== STOP-LIST ({total} ta pozitsiya) ===")
    if not total:
        print("  Hozir hech qayerda stop yo'q.")
        return
    for tg_id, items in stops.items():
        if not items:
            continue
        print(f"\n  {tg_names.get(tg_id, tg_id)}  [{tg_id}]")
        for pid, balance in items.items():
            nm = names.get(pid, "")
            extra = f"   qoldiq={balance}" if balance is not None else ""
            print(f"    {pid}  {nm or '(nomi topilmadi)'}{extra}")
            if raw:
                print("      " + json.dumps({"productId": pid, "balance": balance},
                                            ensure_ascii=False))


def main():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return
    raw = "--raw" in args
    want = {a for a in args if a.startswith("--") and a != "--raw"}

    creds = get_credentials()
    if not creds["api_key"]:
        print("apiKey topilmadi.")
        print("MAXWAY_IIKO_LOGIN env o'zgaruvchisini bering yoki iiko_login.txt yarating.")
        sys.exit(1)
    mode = "v2 (apiKey+appId+clientSecret)" if creds["app_id"] and creds["client_secret"] \
        else "v1 (apiLogin)"
    print(f"Avtorizatsiya usuli: {mode}")

    client = IikoClient()
    try:
        client.token()
        print("✓ Token olindi")
        orgs = client.organizations()
    except IikoError as e:
        print("✗", e)
        sys.exit(1)

    show_orgs(orgs)
    if want == {"--orgs"}:
        return
    org_ids = [o["id"] for o in orgs if o.get("id")]
    if not org_ids:
        print("\nTashkilot topilmadi — apiKey qaysi tashkilotga bog'langanini tekshiring.")
        return

    try:
        groups = client.terminal_groups(org_ids)
    except IikoError as e:
        print("✗ Terminal guruhlar olinmadi:", e)
        return
    show_terminals(groups, orgs)
    if want == {"--terminals"}:
        return

    try:
        stops = client.stop_lists(org_ids)
    except IikoError as e:
        print("✗ Stop-list olinmadi:", e)
        return
    names = {}
    if any(stops.values()):
        print("\n  Nomenklatura yuklanmoqda (taom nomlarini topish uchun)...")
        pids = set()
        for v in stops.values():
            pids |= set(v)
        names = client.resolve_names(org_ids, pids)
    show_stops(stops, groups, names, raw)
    print("\nKeyingi qadam: yuqoridagi terminal guruh ID larini filiallarga bog'lash.")


if __name__ == "__main__":
    main()
