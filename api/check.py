import re
import json
import requests
import html
import urllib3
from typing import Optional, Dict, Any

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://panel.lunafy.run"
INITIAL_COOKIES = {
    "pelican_session": "eyJpdiI6IjhKcFR6cCtKMTdaVHozc2JFM041K3c9PSIsInZhbHVlIjoiQ21Ua21LcnVJVWVMUkNMekhub2o1Q1ZKU3l5VWpZRzdwWG9PbmluV2NqR3ZVanFGeVVFRHcvd1NKMzZBdFlzdVArWnc1RzF0c3ZuUWJ1WVdtblF3WVJKR2RvZlJueitMcWd1NzhDeVBzdVdiWFYzaHF3ZlpJcGNuQzlSeVZOZ3kiLCJtYWMiOiI1NzYxOTNiMjAwMzA0YzJiZTJjZDc2MTYyNmRkMzhlYWM2OTU3NjczYzA4NGM2NWIyYWVlOTU5YzVkM2MwMjZmIiwidGFnIjoiIn0%3D"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

def create_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    for name, value in INITIAL_COOKIES.items():
        session.cookies.set(name, value, domain="panel.lunafy.run")
    return session

def extract_csrf_token(html_text: str) -> Optional[str]:
    match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html_text)
    return match.group(1) if match else None

def is_logged_in(html_text: str) -> bool:
    return "Dashboard" in html_text and "server-status-widget" in html_text

def extract_server_status_widget(html_text: str) -> Optional[Dict[str, Any]]:
    pattern = r'<div\b[^>]*?\bwire:snapshot=[\'"]({[^\'"]+?})[\'"][^>]*?>'
    for match in re.finditer(pattern, html_text, re.DOTALL):
        snap_str = match.group(1)
        div_tag = match.group(0)
        snap_str_decoded = html.unescape(snap_str).replace('&quot;', '"')
        try:
            data = json.loads(snap_str_decoded)
        except json.JSONDecodeError:
            continue
        if data.get('memo', {}).get('name') == 'app.custom.filament.widgets.server-status-widget':
            wire_id_match = re.search(r'wire:id="([^"]+)"', div_tag)
            wire_id = wire_id_match.group(1) if wire_id_match else None
            lazy_match = re.search(r'x-intersect="\$wire\.__lazyLoad\(&#039;([^&#]+)&#039;\)"', div_tag)
            lazy_param = lazy_match.group(1) if lazy_match else None
            return {
                "wire_id": wire_id,
                "snapshot": data,
                "checksum": data.get('checksum'),
                "lazy_param": lazy_param,
                "lazy_loaded": data['memo'].get('lazyLoaded', False),
            }
    return None

def post_livewire_update(session, csrf_token: str, components: list) -> dict:
    url = f"{BASE_URL}/livewire/update"
    payload = {"_token": csrf_token, "components": components}
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "X-Livewire": "true",
        "Content-Type": "application/json",
        "Referer": BASE_URL + "/",
        "Origin": BASE_URL,
    }
    resp = session.post(url, json=payload, headers=headers, timeout=20, verify=False)
    resp.raise_for_status()
    return resp.json()

def check_and_renew() -> dict:
    """Thực hiện kiểm tra và renew, trả về kết quả."""
    result = {"status": "unknown", "message": ""}
    session = create_session()

    # 1. GET trang chủ
    try:
        resp = session.get(BASE_URL, timeout=20, verify=False)
        html_text = resp.text
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Lỗi kết nối: {e}"
        return result

    if not is_logged_in(html_text):
        result["status"] = "error"
        result["message"] = "Cookie hết hạn hoặc không hợp lệ (trang login)."
        return result

    csrf_token = extract_csrf_token(html_text)
    if not csrf_token:
        result["status"] = "error"
        result["message"] = "Không tìm thấy CSRF token."
        return result

    widget = extract_server_status_widget(html_text)
    if not widget:
        result["status"] = "error"
        result["message"] = "Không tìm thấy widget server-status."
        return result

    # Nếu widget có lazy_param thì gọi lazy load
    html_response = html_text
    if widget['lazy_param']:
        component = {
            "snapshot": json.dumps(widget["snapshot"], separators=(',', ':')),
            "updates": {},
            "calls": [{"path": "", "method": "__lazyLoad", "params": [widget["lazy_param"]]}]
        }
        lazy_resp = post_livewire_update(session, csrf_token, [component])
        comp = lazy_resp["components"][0]
        html_response = comp.get("effects", {}).get("html", "")
        widget["snapshot"] = json.loads(comp["snapshot"])

    # Kiểm tra trạng thái
    if "Your servers have been deleted. Renew to create a new one." in html_response:
        # Renew
        renew_component = {
            "snapshot": json.dumps(widget["snapshot"], separators=(',', ':')),
            "updates": {},
            "calls": [{"path": "", "method": "renew", "params": []}]
        }
        renew_resp = post_livewire_update(session, csrf_token, [renew_component])
        renew_html = renew_resp["components"][0].get("effects", {}).get("html", "")
        if "Next renewal" in renew_html:
            match = re.search(r"Next renewal\s*:\s*(\d{2}/\d{2}\s+\d{2}:\d{2})", renew_html)
            if match:
                result["status"] = "renewed"
                result["message"] = f"Renew thành công! Next renewal: {match.group(1)}"
            else:
                result["status"] = "renewed"
                result["message"] = "Renew thành công (không rõ ngày)."
        elif "Discord Server Required" in renew_html:
            result["status"] = "error"
            result["message"] = "Cần tham gia Discord server để renew."
        else:
            result["status"] = "error"
            result["message"] = "Renew không thành công."
    elif "Next renewal" in html_response:
        match = re.search(r"Next renewal\s*:\s*(\d{2}/\d{2}\s+\d{2}:\d{2})", html_response)
        if match:
            result["status"] = "active"
            result["message"] = f"Server đang hoạt động. Next renewal: {match.group(1)}"
        else:
            result["status"] = "active"
            result["message"] = "Server đang hoạt động."
    elif "Active" in html_response:
        result["status"] = "active"
        result["message"] = "Server đang hoạt động (Active)."
    else:
        result["status"] = "unknown"
        result["message"] = "Không xác định được trạng thái."

    return result
