"""Telegram kanal/guruh ID sini topish va sozlamani tekshirish.

Ishlatish (loyiha papkasidan):

    python tools/tg_chat_id.py                 # bot ko'rgan barcha chatlar ro'yxati
    python tools/tg_chat_id.py --check -1001234567890   # shu chatga yoza oladimi
    python tools/tg_chat_id.py --send -1001234567890    # sinov xabarini YUBORADI

Token qayerdan olinadi: MAXWAY_BOT_TOKEN env yoki telegram_token.txt fayl
(main.py dagi get_bot_token bilan bir xil mantiq).

MUHIM: yopiq kanal ID si `-100` bilan boshlanadi (masalan -1001234567890).
Bot kanalga ADMINISTRATOR qilib qo'shilgan bo'lishi shart.
"""
import json
import os
import sys
import urllib.parse
import urllib.request


def get_bot_token() -> str:
    tok = os.environ.get("MAXWAY_BOT_TOKEN", "").strip()
    if not tok:
        for name in ("telegram_token.txt", "../telegram_token.txt"):
            try:
                with open(name, encoding="utf-8") as f:
                    tok = f.read().strip()
                break
            except FileNotFoundError:
                continue
    if "=" in tok:
        tok = tok.split("=", 1)[1].strip()
    return tok


def api(token: str, method: str, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": str(e)}


def list_chats(token: str):
    """Bot oxirgi kunlarda ko'rgan barcha chatlar."""
    res = api(token, "getUpdates", limit=100, allowed_updates=json.dumps(
        ["message", "channel_post", "my_chat_member"]))
    if not res.get("ok"):
        print("XATO:", res.get("description"))
        if "webhook" in str(res.get("description", "")).lower():
            print("  → Botga webhook o'rnatilgan. getUpdates ishlamaydi.")
            print("  → Forward usulidan foydalaning: kanaldagi xabarni @userinfobot ga yuboring.")
        return
    chats = {}
    for u in res["result"]:
        for key in ("message", "channel_post", "my_chat_member"):
            if key in u and "chat" in u[key]:
                c = u[key]["chat"]
                chats[c["id"]] = (c.get("type", "?"),
                                  c.get("title") or c.get("username") or c.get("first_name") or "—")
    if not chats:
        print("Hech qanday chat topilmadi.\n")
        print("Sabablari:")
        print("  1. Bot kanalga hali qo'shilmagan yoki admin emas")
        print("  2. Bot qo'shilgandan KEYIN kanalga hech narsa yozilmagan")
        print("     → Kanalga bitta xabar yozing va skriptni qayta ishga tushiring")
        print("  3. Telegram yangilanishlarni 24 soatdan keyin o'chiradi")
        return
    print(f"{'CHAT ID':<20}{'TURI':<12}NOMI")
    print("-" * 62)
    for cid, (typ, title) in sorted(chats.items()):
        mark = "  ← kanal" if typ == "channel" else ""
        print(f"{cid:<20}{typ:<12}{title}{mark}")
    print()
    print("Kanal ID sini MAXWAY_STOP_CHANNEL ga yozing (Railway → Variables).")


def check(token: str, chat_id: str):
    """Chat mavjudmi va bot unga yoza oladimi — xabar YUBORMASDAN tekshiradi."""
    info = api(token, "getChat", chat_id=chat_id)
    if not info.get("ok"):
        print("✗ Chat topilmadi:", info.get("description"))
        print("  ID to'g'rimi? Yopiq kanal -100 bilan boshlanadi.")
        return False
    c = info["result"]
    print(f"✓ Chat: {c.get('title') or c.get('username')}  (turi: {c.get('type')})")

    me = api(token, "getMe")
    if not me.get("ok"):
        print("✗ Token yaroqsiz:", me.get("description"))
        return False
    bot_id = me["result"]["id"]
    print(f"✓ Bot: @{me['result'].get('username')}")

    m = api(token, "getChatMember", chat_id=chat_id, user_id=bot_id)
    if not m.get("ok"):
        print("✗ Bot bu kanalda emas:", m.get("description"))
        return False
    st = m["result"].get("status")
    can_post = m["result"].get("can_post_messages")
    if st == "administrator" and (can_post or c.get("type") != "channel"):
        print("✓ Bot administrator va xabar yubora oladi — sozlash TO'G'RI")
        return True
    if st == "administrator":
        print("✗ Bot administrator, lekin «Отправка сообщений» huquqi yo'q")
    else:
        print(f"✗ Botning holati: {st} — administrator qilib qo'ying")
    return False


def send_test(token: str, chat_id: str):
    """Kanalga haqiqiy sinov xabarini yuboradi."""
    res = api(token, "sendMessage", chat_id=chat_id,
              text="✅ MAXWAY: стоп-лист уведомления настроены", parse_mode="HTML")
    if res.get("ok"):
        print("✓ Sinov xabari yuborildi — kanalni tekshiring")
    else:
        print("✗ Yuborilmadi:", res.get("description"))


def main():
    token = get_bot_token()
    if not token:
        print("Bot token topilmadi.")
        print("MAXWAY_BOT_TOKEN env o'zgaruvchisini bering yoki telegram_token.txt yarating.")
        sys.exit(1)
    args = sys.argv[1:]
    if not args:
        list_chats(token)
    elif args[0] == "--check" and len(args) > 1:
        check(token, args[1])
    elif args[0] == "--send" and len(args) > 1:
        send_test(token, args[1])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
