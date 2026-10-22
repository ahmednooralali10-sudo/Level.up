# -*- coding: utf-8 -*-
import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web

# جدول مستويات الخبرة (EXP)
EXP_TABLE: Dict[int, int] = {
    1: 0, 2: 48, 3: 202, 4: 544, 5: 1012, 6: 1844, 7: 2792, 8: 3800,
    9: 4870, 10: 6004, 11: 7192, 12: 8448, 13: 9760, 14: 11140, 15: 12566,
    16: 14060, 17: 15610, 18: 17224, 19: 18902, 20: 20632, 21: 22424, 22: 24278,
    23: 26192, 24: 28166, 25: 30200, 26: 32294, 27: 34448, 28: 37804, 29: 41274,
    30: 44870, 31: 48582, 32: 53394, 33: 58566, 34: 64096, 35: 69994, 36: 76460,
    37: 83506, 38: 91128, 39: 99322, 40: 108092, 41: 120144, 42: 133266, 43: 147472,
    44: 162760, 45: 179126, 46: 196572, 47: 215368, 48: 235516, 49: 257010, 50: 279860,
    51: 304056, 52: 348318, 53: 394982, 54: 444044, 55: 495508, 56: 549364, 57: 633756,
    58: 721744, 59: 813336, 60: 908522, 61: 1041438, 62: 1180352, 63: 1325266,
    64: 1476184, 65: 1634300, 66: 1840946, 67: 2056594, 68: 2281242, 69: 2514880,
    70: 2757530, 71: 3059506, 72: 3372284, 73: 3699456, 74: 4041030, 75: 4397002,
    76: 4829104, 77: 5282204, 78: 5756304, 79: 6251408, 80: 6776502, 81: 7381324,
    82: 8043154, 83: 8752982, 84: 9510808, 85: 10316338, 86: 11277190, 87: 12291748,
    88: 13360304, 89: 14482858, 90: 15659418, 91: 17026708, 92: 18453950, 93: 19941280,
    94: 21488570, 95: 23095858, 96: 24763138, 97: 26490428, 98: 28378704, 99: 30124996,
    100: 32032884
}

def calculate_level_progress(level: int, current_exp: int) -> Dict[str, Any]:
    level = max(1, level)
    next_level = min(100, level + 1)
    base_exp = EXP_TABLE.get(level, 0)
    target_exp = EXP_TABLE.get(next_level, base_exp + 50000)
    
    needed_for_level = max(1, target_exp - base_exp)
    earned_in_level = max(0, current_exp - base_exp)
    remaining_exp = max(0, target_exp - current_exp)
    progress_pct = min(100.0, max(0.0, (earned_in_level / needed_for_level) * 100.0))

    return {
        "next_level": next_level, "base_exp": base_exp, "target_exp": target_exp,
        "needed_for_level": needed_for_level, "earned_in_level": earned_in_level,
        "remaining_exp": remaining_exp, "progress_pct": round(progress_pct, 1)
    }

class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_matches_started = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.account_token_map: Dict[str, str] = {}
        self.auth_to_game_id: Dict[str, str] = {}
        self.game_to_auth_id: Dict[str, str] = {}
        self.paused_accounts: set = set()
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.active_writers: Dict[str, set] = {}

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {"time": time.strftime("%H:%M:%S"), "level": level, "message": message, "uid": str(uid) if uid else None}
        self.logs.append(entry)
        if len(self.logs) > self.max_logs: self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int,
                         likes: int = 0, token: Optional[str] = None, auth_uid: Optional[str] = None):
        uid_str = str(uid)
        prog = calculate_level_progress(level or 1, exp)
        lvl_val = level or 1
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str, "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "ID", "level": lvl_val, "current_exp": exp,
                "gained_exp": 0, "progress_pct": prog["progress_pct"],
                "status": "ONLINE", "matches_played": 0, "active_matches": 0
            }
        else:
            acc = self.accounts[uid_str]
            acc["current_exp"] = exp
            acc["level"] = lvl_val
            acc["progress_pct"] = prog["progress_pct"]
            acc["status"] = "ONLINE"
        self.recalc_totals()

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())

bot_state = BotState()

# تصميم صفحة لوحة التحكم مباشرة داخل السيرفر
DASHBOARD_HTML = """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>لوحة تحكم السكواد - RBC</title>
    <style>
        body { font-family: Tahoma, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .container { max-width: 900px; margin: auto; }
        .card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h2, h3 { color: #38bdf8; margin-top: 0; }
        input, button { padding: 12px; margin: 8px 0; border-radius: 6px; border: none; font-size: 14px; }
        input { width: calc(50% - 10px); background: #334155; color: #fff; }
        input[type="text"], input[type="password"] { width: 100%; box-sizing: border-box; }
        button { background: #0284c7; color: #fff; cursor: pointer; font-weight: bold; width: 100%; }
        button:hover { background: #0369a1; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #334155; padding: 12px; text-align: center; }
        th { background: #334155; color: #38bdf8; }
        .status { color: #4ade80; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h2>🎮 لوحة إدارة حسابات سكواد Free Fire</h2>
        
        <div class="card">
            <h3>إضافة حساب جديد للسكواد</h3>
            <form id="accForm">
                <input type="text" id="uid" placeholder="أدخل UID الحساب" required>
                <input type="password" id="password" placeholder="أدخل كلمة المرور (Password)" required>
                <button type="submit">إضافة وحفظ الحساب</button>
            </form>
        </div>

        <div class="card">
            <h3>الحسابات المتصلة حالياً</h3>
            <table>
                <thead>
                    <tr>
                        <th>UID</th>
                        <th>الاسم</th>
                        <th>المستوى</th>
                        <th>المنطقة</th>
                        <th>الحالة</th>
                        <th>المباريات</th>
                    </tr>
                </thead>
                <tbody id="accTable">
                    <tr><td colspan="6">جاري التحميل...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        async function loadStats() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();
                const tbody = document.getElementById('accTable');
                tbody.innerHTML = '';
                
                if (data.accounts.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6">لا توجد حسابات مضافة حالياً</td></tr>';
                    return;
                }

                data.accounts.forEach(acc => {
                    tbody.innerHTML += `
                        <tr>
                            <td>${acc.uid}</td>
                            <td>${acc.nickname}</td>
                            <td>${acc.level}</td>
                            <td>${acc.region}</td>
                            <td class="status">${acc.status}</td>
                            <td>${acc.matches_played}</td>
                        </tr>
                    `;
                });
            } catch (e) { console.error(e); }
        }

        document.getElementById('accForm').onsubmit = async (e) => {
            e.preventDefault();
            const uid = document.getElementById('uid').value;
            const password = document.getElementById('password').value;
            
            const res = await fetch('/api/account/add', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({uid, password})
            });
            const result = await res.json();
            if(result.status === 'ok') {
                alert('تمت إضافة الحساب بنجاح!');
                document.getElementById('uid').value = '';
                document.getElementById('password').value = '';
                loadStats();
            } else {
                alert('خطأ: ' + result.error);
            }
        };

        setInterval(loadStats, 4000);
        loadStats();
    </script>
</body>
</html>
"""

async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=DASHBOARD_HTML, content_type="text/html", charset="utf-8")

async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "accounts": accounts_data,
        "logs": bot_state.logs[-50:],
        "uptime": int(time.time() - bot_state.start_time)
    })

async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        accounts_file = "accounts.json"
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception: pass

        uid = str(data.get("uid", "")).strip()
        pwd = str(data.get("password", "")).strip()
        if not uid or not pwd:
            return web.json_response({"status": "error", "error": "UID and Password are required"})

        existing = [acc for acc in existing if str(acc.get("uid", "")) != uid]
        existing.append({"uid": uid, "password": pwd})

        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        bot_state.log(f"Added account {uid} via web", "success")
        
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})

async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner
