import os
import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# ===========================================================================
# CẤU HÌNH: đọc từ biến môi trường (GitHub Secrets). KHÔNG ghi key vào code.
# ===========================================================================
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
BACKFILL = os.environ.get("BACKFILL", "").lower() == "true"

HEADERS_SUPABASE = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

SCHEME = "https://"
HOST = "www.minhngoc.net.vn"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

STATION_MAP = {
    # Miền Nam
    "TP. HCM": "TPHCM", "TP.HCM": "TPHCM", "TPHCM": "TPHCM", "Đồng Tháp": "DONGTHAP", "Cà Mau": "CAMAU",
    "Bến Tre": "BENTRE", "Vũng Tàu": "VUNGTAU", "Bạc Liêu": "BACLIEU",
    "Đồng Nai": "DONGNAI", "Cần Thơ": "CANTHO", "Sóc Trăng": "SOCTRANG",
    "Tây Ninh": "TAYNINH", "An Giang": "ANGIANG", "Bình Thuận": "BINHTHUAN",
    "Vĩnh Long": "VINHLONG", "Bình Dương": "BINHDUONG", "Trà Vinh": "TRAVINH",
    "Long An": "LONGAN", "Bình Phước": "BINHPHUOC", "Hậu Giang": "HAUGIANG",
    "Tiền Giang": "TIENGIANG", "Kiên Giang": "KIENGIANG", "Đà Lạt": "DALAT",
    # Miền Trung
    "Thừa Thiên Huế": "TTHUE", "T.T.Huế": "TTHUE", "Phú Yên": "PHUYEN", "Đắc Lắc": "DAKLAK",
    "Đắk Lắk": "DAKLAK", "Quảng Nam": "QUANGNAM", "Đà Nẵng": "DANANG", "Khánh Hòa": "KHANHHOA",
    "Bình Định": "BINHDINH", "Quảng Trị": "QUANGTRI", "Quảng Bình": "QUANGBINH",
    "Gia Lai": "GIALAI", "Ninh Thuận": "NINHTHUAN", "Quảng Ngãi": "QUANGNGAI",
    "Đắc Nông": "DAKNONG", "Kon Tum": "KONTUM",
}


def extract_2d_lo(prizes_raw):
    """Lấy 2 số cuối của tất cả các giải."""
    lo_set = []
    for p in prizes_raw:
        clean_p = re.sub(r"\D", "", str(p))
        if len(clean_p) >= 2:
            lo_set.append(clean_p[-2:])
    return lo_set


def split_numbers(text):
    """Tách chuỗi '123 - 456 - 789' thành list số."""
    return [re.sub(r"\D", "", n) for n in text.split("-") if re.sub(r"\D", "", n)]


# ==================== 1. CÀO MIỀN BẮC ====================
def scrape_minhngoc_mb(date_str):
    url = f"{SCHEME}{HOST}/ket-qua-xo-so/ket-qua-xoso-mien-bac/{date_str.strip()}.html"
    try:
        res = requests.get(url, headers=UA, timeout=15)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        box_table = soup.find("table", class_="bkqtmb")
        if not box_table:
            return None

        prizes_raw = []
        special_prize = ""
        gdb_cell = box_table.find("td", class_="gdb")
        if gdb_cell:
            special_prize = re.sub(r"\D", "", gdb_cell.text.strip())
            if special_prize:
                prizes_raw.append(special_prize)

        g7_numbers = []
        for td in box_table.find_all("td"):
            classes = td.get("class", [])
            if "g7" in classes:
                g7_numbers.extend(split_numbers(td.text))
            elif any(c in classes for c in ["g1", "g2", "g3", "g4", "g5", "g6"]):
                prizes_raw.extend(split_numbers(td.text))

        prizes_raw.extend(g7_numbers)
        if not prizes_raw or not special_prize:
            return None  # chưa có kết quả

        db_date = datetime.datetime.strptime(date_str, "%d-%m-%Y").strftime("%Y-%m-%d")
        return {
            "station_id": "MB",
            "draw_date": db_date,
            "special_prize": special_prize,
            "seventh_or_eighth": g7_numbers,
            "lo_numbers": extract_2d_lo(prizes_raw),
        }
    except Exception as e:
        print(f"❌ Lỗi cào MB ngày {date_str}: {e}")
        return None


# ==================== 2. CÀO MIỀN NAM & MIỀN TRUNG ====================
def scrape_minhngoc_mn_mt(region_code, date_str):
    url = f"{SCHEME}{HOST}/ket-qua-xo-so/{region_code}/{date_str.strip()}.html"
    try:
        res = requests.get(url, headers=UA, timeout=15)
        if res.status_code != 200:
            return []

        soup = BeautifulSoup(res.text, "html.parser")
        box_table = soup.find("table", class_=re.compile(r"bkqtmiennam|bkqtmientrung"))
        if not box_table:
            return []

        header_row = box_table.find("tr", class_="header")
        if not header_row:
            return []

        station_names = [td.text.strip() for td in header_row.find_all("td") if td.text.strip()]
        station_results = {name: {"special": "", "g8": [], "raw_prizes": []} for name in station_names}

        for row in box_table.find_all("tr"):
            tds = row.find_all("td")
            if len(tds) <= 1:
                continue

            prize_name = tds[0].text.strip()  # SỬA: trước đây là tds.text (lỗi)
            for idx, td in enumerate(tds[1:]):
                if idx >= len(station_names):
                    continue
                st_name = station_names[idx]
                nums = split_numbers(td.text)
                if not nums:
                    continue

                if prize_name in ["G.8", "Giải 8", "Giải Tám"]:
                    station_results[st_name]["g8"].extend(nums)
                elif prize_name in ["ĐB", "Giải ĐB", "Giải Đặc Biệt"]:
                    station_results[st_name]["special"] = nums[0]  # SỬA: lấy 1 số, không phải list

                station_results[st_name]["raw_prizes"].extend(nums)

        db_date = datetime.datetime.strptime(date_str, "%d-%m-%Y").strftime("%Y-%m-%d")
        records = []
        for name, data in station_results.items():
            st_id = STATION_MAP.get(name)
            if not st_id:
                if data["raw_prizes"]:
                    print(f"⚠️ Chưa có trong STATION_MAP: '{name}'")
                continue
            if data["raw_prizes"] and data["special"]:
                records.append({
                    "station_id": st_id,
                    "draw_date": db_date,
                    "special_prize": data["special"],
                    "seventh_or_eighth": data["g8"],
                    "lo_numbers": extract_2d_lo(data["raw_prizes"]),
                })
        return records
    except Exception as e:
        print(f"❌ Lỗi cào {region_code} ngày {date_str}: {e}")
        return []


# ==================== 3. LƯU & DỌN DẸP SUPABASE ====================
def get_existing_count(station_id):
    url = f"{SUPABASE_URL}/rest/v1/draw_results?station_id=eq.{station_id}&select=id"
    try:
        res = requests.get(url, headers=HEADERS_SUPABASE, timeout=10)
        if res.status_code == 200 and isinstance(res.json(), list):
            return len(res.json())
    except Exception as e:
        print(f"❌ Lỗi kiểm tra đài {station_id}: {e}")
    return 0


def save_to_supabase(data):
    if not data:
        return
    # SỬA: on_conflict để chạy lặp nhiều lần/ngày không bị trùng
    endpoint = f"{SUPABASE_URL}/rest/v1/draw_results?on_conflict=station_id,draw_date"
    try:
        resp = requests.post(endpoint, json=data, headers=HEADERS_SUPABASE, timeout=10)
        if resp.status_code in (200, 201, 204):
            print(f"✅ Đã lưu {data['station_id']} ngày {data['draw_date']}")
        else:
            print(f"❌ Lỗi lưu [{data['station_id']}]: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"❌ Lỗi kết nối Supabase [{data['station_id']}]: {e}")


def clean_rolling_50(station_id):
    """Giữ đúng 50 kỳ mới nhất của mỗi đài."""
    url = (f"{SUPABASE_URL}/rest/v1/draw_results?station_id=eq.{station_id}"
           f"&select=id&order=draw_date.desc&offset=50")
    try:
        res = requests.get(url, headers=HEADERS_SUPABASE, timeout=10).json()
        if res and isinstance(res, list):
            old_ids = [str(row["id"]) for row in res]
            delete_url = f"{SUPABASE_URL}/rest/v1/draw_results?id=in.({','.join(old_ids)})"
            requests.delete(delete_url, headers=HEADERS_SUPABASE, timeout=10)
            print(f"🧹 Dọn {len(old_ids)} kỳ cũ của đài {station_id}")
    except Exception as e:
        print(f"Lỗi dọn dẹp đài {station_id}: {e}")


# ==================== 4. CHƯƠNG TRÌNH CHÍNH ====================
if __name__ == "__main__":
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
    today_str = today.strftime("%d-%m-%Y")
    print(f"🚀 Bắt đầu cào ngày {today_str} (backfill={BACKFILL})")

    # Miền Bắc: 1 kỳ/ngày nên 50 ngày là đủ 50 kỳ
    mb_days = 50 if (BACKFILL or get_existing_count("MB") < 50) else 1
    for i in range(mb_days):
        d_str = (today - datetime.timedelta(days=i)).strftime("%d-%m-%Y")
        item = scrape_minhngoc_mb(d_str)
        if item:
            save_to_supabase(item)
        time.sleep(0.3)
    clean_rolling_50("MB")

    # Miền Nam + Miền Trung: mỗi đài ~1 kỳ/tuần, nạp lịch sử cần ~350 ngày
    days_back = 350 if BACKFILL else 1
    touched = set()
    for i in range(days_back):
        d_str = (today - datetime.timedelta(days=i)).strftime("%d-%m-%Y")
        for region in ("mien-nam", "mien-trung"):
            for item in scrape_minhngoc_mn_mt(region, d_str):
                save_to_supabase(item)
                touched.add(item["station_id"])
        time.sleep(0.3)

    for sid in touched:
        clean_rolling_50(sid)

    print("🎉 Xong!")
