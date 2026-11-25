"""
Máy chủ tiếp nhận tin báo Toàn dân Bảo vệ Rừng (dành cho Chi cục / Hạt Kiểm lâm).
Hỗ trợ:
  1. Tiếp nhận ảnh hiện trường + tọa độ WGS-84 & VN-2000 từ ứng dụng Android.
  2. Cập nhật trạng thái xử lý (DANG_XAC_MINH / DA_XU_LY) và phản hồi ngược lại cho người dân.
  3. Xuất toàn bộ điểm báo cáo ra định dạng GeoJSON chuẩn để mở trực tiếp trên QGIS / MapInfo.
"""

import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAPS_DIR = BASE_DIR / "maps"
MAPS_DIR.mkdir(exist_ok=True)
DB_PATH = BASE_DIR / "kiemlam_reports.db"

security = HTTPBasic()
ADMIN_USER = os.getenv("ADMIN_USER", "Admin_huydinh")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Hoangthienlong88@2026")


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username, ADMIN_USER)
    ok_pass = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chỉ Quản trị viên được ủy quyền mới có quyền truy cập",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app = FastAPI(title="Cổng Tiếp Nhận Tin Báo Toàn Dân Bảo Vệ Rừng")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/maps", StaticFiles(directory=str(MAPS_DIR)), name="maps")


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                server_id TEXT PRIMARY KEY,
                local_id TEXT,
                category TEXT,
                urgency TEXT,
                description TEXT,
                latitude REAL,
                longitude REAL,
                accuracy_meters REAL,
                vn2000_x REAL,
                vn2000_y REAL,
                vn2000_zone TEXT,
                azimuth_deg REAL,
                is_anonymous INTEGER,
                reporter_name TEXT,
                reporter_phone TEXT,
                photo_filename TEXT,
                created_at TEXT,
                status TEXT DEFAULT 'DA_GUI',
                authority_response TEXT DEFAULT ''
            )
            """
        )


def init_sos_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sos_beacons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                officer_name TEXT,
                unit_name TEXT,
                latitude REAL,
                longitude REAL,
                accuracy_meters REAL,
                vn2000_x REAL,
                vn2000_y REAL,
                vn2000_zone TEXT,
                received_at TEXT
            )
            """
        )


init_db()
def init_fire_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fire_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location_name TEXT,
                latitude REAL,
                longitude REAL,
                vn2000_x REAL,
                vn2000_y REAL,
                confidence TEXT,
                source TEXT,
                detected_at TEXT
            )
            """
        )
        # Chèn 1 điểm mẫu khu vực Lâm Đồng nếu bảng còn trống để cán bộ kiểm thử ngay
        count = conn.execute("SELECT COUNT(*) FROM fire_alerts").fetchone()[0]
        if count == 0:
            conn.execute(
                """
                INSERT INTO fire_alerts (location_name, latitude, longitude, vn2000_x, vn2000_y, confidence, source, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Tiểu khu 144B - Khu vực Đà Lạt (Điểm mẫu kiểm thử)", 11.9652, 108.4810, 1323120.5, 579640.2, "Cao (85%)", "VIIRS/Sentinel-2", datetime.now().isoformat(timespec="minutes")),
            )


init_sos_table()
def init_admin_tables():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS officer_registrations (
                device_id TEXT PRIMARY KEY,
                full_name TEXT,
                unit_name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'PENDING',
                approved_token TEXT DEFAULT '',
                requested_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS map_layers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer_code TEXT UNIQUE,
                title TEXT,
                category TEXT,
                version TEXT,
                access_level TEXT DEFAULT 'PUBLIC',
                filename TEXT,
                file_size_mb REAL,
                updated_at TEXT
            )
            """
        )


init_fire_table()
def init_inventory_tables():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_plots (
                project_code TEXT,
                plot_code TEXT,
                target_area_m2 INTEGER,
                center_lat REAL,
                center_lon REAL,
                center_vn2000_x REAL,
                center_vn2000_y REAL,
                updated_at TEXT,
                PRIMARY KEY (project_code, plot_code)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_members (
                project_code TEXT,
                device_id TEXT,
                member_name TEXT,
                latitude REAL,
                longitude REAL,
                vn2000_x REAL,
                vn2000_y REAL,
                accuracy_meters REAL,
                updated_at TEXT,
                PRIMARY KEY (project_code, device_id)
            )
            """
        )


init_admin_tables()
def init_basemap_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS satellite_basemaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                year INTEGER DEFAULT 2026,
                month INTEGER DEFAULT 1,
                month_label TEXT,
                tile_url TEXT DEFAULT '',
                filename TEXT DEFAULT '',
                preview_filename TEXT DEFAULT '',
                north_lat REAL DEFAULT 12.15,
                south_lat REAL DEFAULT 11.75,
                east_lon REAL DEFAULT 108.68,
                west_lon REAL DEFAULT 108.25,
                file_size_mb REAL DEFAULT 0.0,
                updated_at TEXT
            )
            """
        )
        existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(satellite_basemaps)").fetchall()}
        for col_name, col_def in [
            ("preview_filename", "TEXT DEFAULT ''"),
            ("north_lat", "REAL DEFAULT 12.15"),
            ("south_lat", "REAL DEFAULT 11.75"),
            ("east_lon", "REAL DEFAULT 108.68"),
            ("west_lon", "REAL DEFAULT 108.25"),
        ]:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE satellite_basemaps ADD COLUMN {col_name} {col_def}")


init_inventory_tables()
def init_legal_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS legal_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_symbol TEXT,
                title TEXT,
                doc_type TEXT,
                summary TEXT,
                doc_url TEXT DEFAULT '',
                filename TEXT DEFAULT '',
                updated_at TEXT
            )
            """
        )
        if conn.execute("SELECT COUNT(*) FROM legal_documents").fetchone()[0] == 0:
            now_iso = datetime.now().isoformat(timespec="minutes")
            seed = [
                ("16/2017/QH14", "Luật Lâm nghiệp", "Luật", "Quy định quản lý, bảo vệ, phát triển, sử dụng rừng, chế biến và thương mại lâm sản.", "", "", now_iso),
                ("156/2018/NĐ-CP", "Nghị định quy định chi tiết thi hành một số điều của Luật Lâm nghiệp", "Nghị định", "Quy định phân loại rừng, chuyển mục đích sử dụng rừng, DVMTR và tổ chức Kiểm lâm.", "", "", now_iso),
                ("91/2024/NĐ-CP", "Nghị định sửa đổi, bổ sung một số điều của Nghị định 156/2018/NĐ-CP", "Nghị định", "Cập nhật quy định chuyển mục đích sử dụng rừng, tạm sử dụng rừng và trồng rừng thay thế.", "", "", now_iso),
                ("33/2018/TT-BNNPTNT", "Thông tư quy định về điều tra, kiểm kê và theo dõi diễn biến rừng", "Thông tư", "Hướng dẫn phương pháp lập ÔTC, đo đếm lâm phần và mẫu biểu điều tra kiểm kê rừng.", "", "", now_iso),
            ]
            conn.executemany(
                "INSERT INTO legal_documents (doc_symbol, title, doc_type, summary, doc_url, filename, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                seed,
            )


init_basemap_table()
init_legal_table()

@app.post("/api/v1/reports")
async def receive_report(
    local_id: str = Form(...),
    category: str = Form(...),
    urgency: str = Form(...),
    description: str = Form(""),
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy_meters: float = Form(0.0),
    vn2000_x: float = Form(...),
    vn2000_y: float = Form(...),
    vn2000_zone: str = Form("Lâm Đồng (107°45')"),
    azimuth_deg: float = Form(0.0),
    is_anonymous: bool = Form(True),
    reporter_name: str = Form("Ẩn danh"),
    reporter_phone: str = Form(""),
    created_at_millis: int = Form(0),
    photo: UploadFile = File(...),
):
    server_id = f"KL-{uuid.uuid4().hex[:8].upper()}"
    safe_name = f"{server_id}_{Path(photo.filename or 'photo.jpg').name}"
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(await photo.read())

    created_iso = (
        datetime.fromtimestamp(created_at_millis / 1000.0).isoformat()
        if created_at_millis > 0
        else datetime.now().isoformat()
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO reports (
                server_id, local_id, category, urgency, description,
                latitude, longitude, accuracy_meters, vn2000_x, vn2000_y,
                vn2000_zone, azimuth_deg, is_anonymous, reporter_name,
                reporter_phone, photo_filename, created_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DA_GUI')
            """,
            (
                server_id, local_id, category, urgency, description,
                latitude, longitude, accuracy_meters, vn2000_x, vn2000_y,
                vn2000_zone, azimuth_deg, int(is_anonymous), reporter_name,
                reporter_phone, safe_name, created_iso,
            ),
        )

    return {"server_id": server_id, "status": "DA_GUI", "message": "Đã tiếp nhận tin báo thành công"}


@app.get("/api/v1/reports/{server_id}/status")
def get_report_status(server_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT server_id, status, authority_response FROM reports WHERE server_id = ?",
            (server_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin báo")
    return {"server_id": row[0], "status": row[1], "authority_response": row[2]}


@app.post("/api/v1/reports/{server_id}/update-status", dependencies=[Depends(require_admin)])
def update_status(
    server_id: str,
    status: str = Form(...),              # DANG_XAC_MINH hoặc DA_XU_LY
    authority_response: str = Form(""),
):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE reports SET status = ?, authority_response = ? WHERE server_id = ?",
            (status, authority_response, server_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Không tìm thấy tin báo")
    return {"server_id": server_id, "status": status, "authority_response": authority_response}


@app.get("/api/v1/reports.geojson", dependencies=[Depends(require_admin)])
def export_geojson():
    """Xuất toàn bộ điểm báo cáo ra GeoJSON để nạp trực tiếp vào QGIS / MapInfo."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM reports ORDER BY created_at DESC").fetchall()
        sos_rows = conn.execute("SELECT * FROM sos_beacons ORDER BY id DESC LIMIT 5").fetchall()
        officer_rows = conn.execute("SELECT * FROM officer_registrations ORDER BY requested_at DESC").fetchall()
        layer_rows = conn.execute("SELECT * FROM map_layers ORDER BY updated_at DESC").fetchall()

    features = []
    for r in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
                "properties": {
                    "server_id": r["server_id"],
                    "category": r["category"],
                    "urgency": r["urgency"],
                    "description": r["description"],
                    "vn2000_x": round(r["vn2000_x"], 2),
                    "vn2000_y": round(r["vn2000_y"], 2),
                    "vn2000_zone": r["vn2000_zone"],
                    "azimuth_deg": r["azimuth_deg"],
                    "status": r["status"],
                    "authority_response": r["authority_response"],
                    "photo_url": f"/uploads/{r['photo_filename']}",
                    "created_at": r["created_at"],
                },
            }
        )
    return JSONResponse({"type": "FeatureCollection", "features": features})


@app.post("/api/v1/sos")
async def receive_sos(
    session_id: str = Form(...),
    officer_name: str = Form("Cán bộ Kiểm lâm"),
    unit_name: str = Form("Chi cục Kiểm lâm tỉnh Lâm Đồng"),
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy_meters: float = Form(0.0),
    vn2000_x: float = Form(...),
    vn2000_y: float = Form(...),
    vn2000_zone: str = Form("Lâm Đồng (107°45')"),
):
    now_iso = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sos_beacons (
                session_id, officer_name, unit_name, latitude, longitude,
                accuracy_meters, vn2000_x, vn2000_y, vn2000_zone, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id, officer_name, unit_name, latitude, longitude,
                accuracy_meters, vn2000_x, vn2000_y, vn2000_zone, now_iso,
            ),
        )
    return {"server_id": session_id, "status": "SOS_RECEIVED", "message": "Đã tiếp nhận tín hiệu SOS khẩn cấp"}


@app.get("/api/v1/fire-alerts")
def list_fire_alerts():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM fire_alerts ORDER BY id DESC LIMIT 30").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/v1/fire-alerts", dependencies=[Depends(require_admin)])
def add_fire_alert(
    location_name: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    vn2000_x: float = Form(0.0),
    vn2000_y: float = Form(0.0),
    confidence: str = Form("Cao"),
    source: str = Form("Trực ban Kiểm lâm / NASA FIRMS"),
):
    now_iso = datetime.now().isoformat(timespec="minutes")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO fire_alerts (location_name, latitude, longitude, vn2000_x, vn2000_y, confidence, source, detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (location_name, latitude, longitude, vn2000_x, vn2000_y, confidence, source, now_iso),
        )
    return {"status": "OK", "message": "Đã thêm điểm cảnh báo cháy rừng"}


@app.post("/api/v1/auth/request-officer")
def request_officer_access(
    device_id: str = Form(...),
    full_name: str = Form(...),
    unit_name: str = Form(...),
    phone: str = Form(...),
):
    now_iso = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO officer_registrations (device_id, full_name, unit_name, phone, status, requested_at)
            VALUES (?, ?, ?, ?, 'PENDING', ?)
            ON CONFLICT(device_id) DO UPDATE SET
                full_name=excluded.full_name,
                unit_name=excluded.unit_name,
                phone=excluded.phone,
                status='PENDING',
                requested_at=excluded.requested_at
            """,
            (device_id, full_name, unit_name, phone, now_iso),
        )
    return {"server_id": device_id, "status": "PENDING", "message": "Đã gửi yêu cầu phê duyệt Cán bộ"}


@app.get("/api/v1/auth/check-status/{device_id}")
def check_officer_status(device_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM officer_registrations WHERE device_id = ?", (device_id,)
        ).fetchone()
    if not row:
        return {"device_id": device_id, "status": "NONE", "approved_token": "", "full_name": "", "unit_name": ""}
    return dict(row)


@app.post("/api/v1/admin/officers/{device_id}/decision", dependencies=[Depends(require_admin)])
def decide_officer(device_id: str, action: str = Form(...)):
    new_status = "APPROVED" if action == "APPROVE" else "REVOKED"
    token = f"TKN-{uuid.uuid4().hex[:12].upper()}" if new_status == "APPROVED" else ""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE officer_registrations SET status = ?, approved_token = ? WHERE device_id = ?",
            (new_status, token, device_id),
        )
    return {"device_id": device_id, "status": new_status, "approved_token": token}


@app.get("/api/v1/map-layers")
def list_map_layers(role: str = "CITIZEN"):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if role == "RANGER":
            rows = conn.execute("SELECT * FROM map_layers ORDER BY updated_at DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM map_layers WHERE access_level = 'PUBLIC' ORDER BY updated_at DESC"
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["download_url"] = f"/maps/{d['filename']}"
        result.append(d)
    return result


@app.post("/api/v1/admin/map-layers", dependencies=[Depends(require_admin)])
async def upload_map_layer(
    layer_code: str = Form(...),
    title: str = Form(...),
    category: str = Form(...),       # HIEN_TRANG_RUNG / QUY_HOACH_LAM_NGHIEP / RANH_GIOI_TIEU_KHU
    version: str = Form(...),        # VD: v2026.11
    access_level: str = Form("RANGER_ONLY"),  # PUBLIC hoặc RANGER_ONLY
    mbtiles_file: UploadFile = File(...),
):
    safe_name = f"{layer_code}_{version}_{Path(mbtiles_file.filename or 'layer.mbtiles').name}"
    dest = MAPS_DIR / safe_name
    content = await mbtiles_file.read()
    dest.write_bytes(content)
    size_mb = round(len(content) / (1024.0 * 1024.0), 2)
    now_iso = datetime.now().isoformat(timespec="minutes")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO map_layers (layer_code, title, category, version, access_level, filename, file_size_mb, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(layer_code) DO UPDATE SET
                title=excluded.title,
                category=excluded.category,
                version=excluded.version,
                access_level=excluded.access_level,
                filename=excluded.filename,
                file_size_mb=excluded.file_size_mb,
                updated_at=excluded.updated_at
            """,
            (layer_code, title, category, version, access_level, safe_name, size_mb, now_iso),
        )
    return {"status": "OK", "layer_code": layer_code, "version": version, "file_size_mb": size_mb}


@app.post("/api/v1/projects/plot-center")
def set_project_plot_center(
    project_code: str = Form(...),
    plot_code: str = Form(...),
    target_area_m2: int = Form(1000),
    center_lat: float = Form(...),
    center_lon: float = Form(...),
    center_vn2000_x: float = Form(...),
    center_vn2000_y: float = Form(...),
):
    now_iso = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO project_plots (
                project_code, plot_code, target_area_m2, center_lat, center_lon,
                center_vn2000_x, center_vn2000_y, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_code, plot_code) DO UPDATE SET
                target_area_m2=excluded.target_area_m2,
                center_lat=excluded.center_lat,
                center_lon=excluded.center_lon,
                center_vn2000_x=excluded.center_vn2000_x,
                center_vn2000_y=excluded.center_vn2000_y,
                updated_at=excluded.updated_at
            """,
            (project_code, plot_code, target_area_m2, center_lat, center_lon, center_vn2000_x, center_vn2000_y, now_iso),
        )
    return {"server_id": f"{project_code}-{plot_code}", "status": "PLOT_CENTER_SET", "message": "Đã chốt Tâm ÔTC"}


@app.post("/api/v1/projects/ping")
def ping_project_position(
    project_code: str = Form(...),
    plot_code: str = Form(...),
    device_id: str = Form(...),
    member_name: str = Form("Cán bộ điều tra"),
    latitude: float = Form(...),
    longitude: float = Form(...),
    vn2000_x: float = Form(...),
    vn2000_y: float = Form(...),
    accuracy_meters: float = Form(0.0),
):
    now_iso = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO project_members (
                project_code, device_id, member_name, latitude, longitude,
                vn2000_x, vn2000_y, accuracy_meters, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_code, device_id) DO UPDATE SET
                member_name=excluded.member_name,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                vn2000_x=excluded.vn2000_x,
                vn2000_y=excluded.vn2000_y,
                accuracy_meters=excluded.accuracy_meters,
                updated_at=excluded.updated_at
            """,
            (project_code, device_id, member_name, latitude, longitude, vn2000_x, vn2000_y, accuracy_meters, now_iso),
        )
        plot_row = conn.execute(
            "SELECT * FROM project_plots WHERE project_code = ? AND plot_code = ?",
            (project_code, plot_code),
        ).fetchone()
        member_rows = conn.execute(
            "SELECT * FROM project_members WHERE project_code = ? ORDER BY updated_at DESC",
            (project_code,),
        ).fetchall()
    return {
        "plot_center": dict(plot_row) if plot_row else None,
        "members": [dict(m) for m in member_rows],
    }


@app.get("/api/v1/satellite-basemaps")
def list_satellite_basemaps(year: Optional[int] = None, month: Optional[int] = None):
    if year is not None and year < 2026:
        return []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if year is not None and month is not None:
            rows = conn.execute(
                "SELECT * FROM satellite_basemaps WHERE year = ? AND month = ? ORDER BY id DESC",
                (year, month),
            ).fetchall()
        elif year is not None:
            rows = conn.execute(
                "SELECT * FROM satellite_basemaps WHERE year = ? ORDER BY month DESC, id DESC",
                (year,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM satellite_basemaps WHERE year >= 2026 ORDER BY year DESC, month DESC, id DESC"
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["download_url"] = f"/maps/{d['filename']}" if d.get("filename") else None
        prev = d.get("preview_filename") or d.get("filename")
        d["preview_url"] = f"/maps/{prev}" if prev else None
        out.append(d)
    return out


@app.post("/api/v1/admin/satellite-basemaps", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def publish_satellite_basemap(
    title: str = Form(...),
    year: int = Form(2026),
    month: int = Form(1),
    tile_url: str = Form(""),
    north_lat: float = Form(12.15),
    south_lat: float = Form(11.75),
    east_lon: float = Form(108.68),
    west_lon: float = Form(108.25),
    geotiff_file: Optional[UploadFile] = File(None),
):
    import re as _re
    try:
        MAPS_DIR.mkdir(parents=True, exist_ok=True)
        month_label = f"Tháng {month}/{year}"
        filename = ""
        preview_filename = ""
        size_mb = 0.0
        if geotiff_file is not None and geotiff_file.filename:
            raw_base = _re.sub(r"[^A-Za-z0-9._-]", "_", Path(geotiff_file.filename).name)
            safe_name = f"basemap_geotiff_{uuid.uuid4().hex[:6]}_{raw_base}"
            dest = MAPS_DIR / safe_name
            total_bytes = 0
            # Ghi tệp GeoTIFF theo từng khối 1 MB để KHÔNG tràn RAM trên Python 32-bit
            with open(dest, "wb") as out_f:
                while True:
                    chunk = await geotiff_file.read(1024 * 1024)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    total_bytes += len(chunk)
            filename = safe_name
            size_mb = round(total_bytes / (1024.0 * 1024.0), 2)
            # Tự động đọc biên WGS-84 & tạo ảnh PNG xem trước (bỏ qua an toàn nếu ảnh quá lớn cho RAM 32-bit)
            try:
                from PIL import Image
                Image.MAX_IMAGE_PIXELS = None
                with Image.open(dest) as img:
                    tags = getattr(img, "tag_v2", {})
                    scale = tags.get(33550)   # ModelPixelScaleTag
                    tie = tags.get(33922)     # ModelTiepointTag
                    if scale and tie and len(scale) >= 2 and len(tie) >= 5:
                        w_val = float(tie[3])
                        n_val = float(tie[4])
                        e_val = w_val + img.width * float(scale[0])
                        s_val = n_val - img.height * float(scale[1])
                        if -180.0 <= w_val <= 180.0 and -90.0 <= n_val <= 90.0 and e_val > w_val and n_val > s_val:
                            west_lon, north_lat, east_lon, south_lat = w_val, n_val, e_val, s_val
                    # Chỉ giải nén ảnh xem trước nếu kích thước ảnh <= 150MB để tránh MemoryError trên Python 32-bit
                    if size_mb <= 150.0:
                        prev_img = img.convert("RGB")
                        prev_img.thumbnail((2048, 2048))
                        prev_name = f"preview_{Path(safe_name).stem}.png"
                        prev_img.save(MAPS_DIR / prev_name, format="PNG", optimize=True)
                        preview_filename = prev_name
            except BaseException:
                preview_filename = ""
        now_iso = datetime.now().isoformat(timespec="minutes")
        init_basemap_table()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO satellite_basemaps (
                    title, year, month, month_label, tile_url, filename, preview_filename,
                    north_lat, south_lat, east_lon, west_lon, file_size_mb, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title, year, month, month_label, tile_url.strip(), filename, preview_filename,
                    north_lat, south_lat, east_lon, west_lon, size_mb, now_iso,
                ),
            )
        return (
            f"<html><meta charset='utf-8'><body style='font-family:sans-serif;padding:24px'>"
            f"<h2 style='color:#14452F'>Đã phát hành ảnh Basemap GeoTIFF thành công!</h2>"
            f"<p><b>Tên ảnh:</b> {title} ({month_label})</p>"
            f"<p><b>Tệp đã lưu:</b> {filename or '(Dùng link Tile XYZ)'} ({size_mb} MB)</p>"
            f"<p><b>Khung tọa độ:</b> Bắc {north_lat:.5f} | Nam {south_lat:.5f} | Đông {east_lon:.5f} | Tây {west_lon:.5f}</p>"
            f"<p><a href='/' style='padding:10px 16px;background:#14452F;color:#fff;text-decoration:none;border-radius:6px'>Quay lại Web Quản trị</a></p>"
            f"</body></html>"
        )
    except Exception as e:
        return HTMLResponse(
            content=(
                f"<html><meta charset='utf-8'><body style='font-family:sans-serif;padding:24px'>"
                f"<h2 style='color:#b91c1c'>Lỗi khi tải ảnh Basemap GeoTIFF</h2>"
                f"<p><b>Chi tiết lỗi:</b> {type(e).__name__}: {e}</p>"
                f"<p><a href='/'>Quay lại Web Quản trị</a></p>"
                f"</body></html>"
            ),
            status_code=200,
        )


@app.get("/api/v1/legal-docs")
def list_legal_docs():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM legal_documents ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["file_url"] = f"/uploads/{d['filename']}" if d["filename"] else None
        out.append(d)
    return out


@app.post("/api/v1/admin/legal-docs", dependencies=[Depends(require_admin)])
async def add_legal_doc(
    doc_symbol: str = Form(...),
    title: str = Form(...),
    doc_type: str = Form("Nghị định"),
    summary: str = Form(""),
    doc_url: str = Form(""),
    doc_file: Optional[UploadFile] = File(None),
):
    filename = ""
    if doc_file is not None and doc_file.filename:
        safe_name = f"legal_{uuid.uuid4().hex[:6]}_{Path(doc_file.filename).name}"
        dest = UPLOAD_DIR / safe_name
        dest.write_bytes(await doc_file.read())
        filename = safe_name
    now_iso = datetime.now().isoformat(timespec="minutes")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO legal_documents (doc_symbol, title, doc_type, summary, doc_url, filename, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_symbol.strip(), title.strip(), doc_type.strip(), summary.strip(), doc_url.strip(), filename, now_iso),
        )
    return {"status": "OK", "doc_symbol": doc_symbol, "title": title}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def dashboard():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM reports ORDER BY created_at DESC").fetchall()
        sos_rows = conn.execute("SELECT * FROM sos_beacons ORDER BY id DESC LIMIT 5").fetchall()
        officer_rows = conn.execute("SELECT * FROM officer_registrations ORDER BY requested_at DESC").fetchall()
        layer_rows = conn.execute("SELECT * FROM map_layers ORDER BY updated_at DESC").fetchall()

    sos_banner = ""
    if sos_rows:
        sos_items = "".join(
            f"<li><b>{s['officer_name']}</b> ({s['unit_name']}) - Mã {s['session_id']} lúc {s['received_at']} | "
            f"VN-2000: X={s['vn2000_x']:.1f}, Y={s['vn2000_y']:.1f} | "
            f"<a href='https://maps.google.com/?q={s['latitude']},{s['longitude']}' target='_blank' style='color:#fff'>Mở bản đồ ứng cứu</a></li>"
            for s in sos_rows
        )
        sos_banner = f"<div style='background:#b71c1c;color:#fff;padding:14px;border-radius:8px;margin-bottom:16px'><h3>CẢNH BÁO SOS KHẨN CẤP TỪ HIỆN TRƯỜNG</h3><ul>{sos_items}</ul></div>"

    items_html = ""
    for r in rows:
        items_html += f"""
        <tr>
            <td><b>{r['server_id']}</b><br><small>{r['created_at']}</small></td>
            <td>{r['category']}<br><small>Mức độ: {r['urgency']}</small></td>
            <td>X: {r['vn2000_x']:.2f}<br>Y: {r['vn2000_y']:.2f}<br><small>{r['vn2000_zone']}</small></td>
            <td>{r['description']}<br><small>Người báo: {r['reporter_name']} {r['reporter_phone']}</small></td>
            <td><a href="/uploads/{r['photo_filename']}" target="_blank"><img src="/uploads/{r['photo_filename']}" width="140" style="border-radius:6px"/></a></td>
            <td>
                <b>{r['status']}</b><br>
                <form method="post" action="/api/v1/reports/{r['server_id']}/update-status" style="margin-top:6px">
                    <select name="status">
                        <option value="DANG_XAC_MINH">Đang xác minh</option>
                        <option value="DA_XU_LY">Đã xử lý xong</option>
                    </select><br>
                    <input type="text" name="authority_response" placeholder="Phản hồi cho người dân..." value="{r['authority_response'] or ''}" style="margin:4px 0;width:180px"/><br>
                    <button type="submit">Cập nhật</button>
                </form>
            </td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="utf-8"/>
        <title>Trung tâm Tiếp nhận Tin báo Bảo vệ Rừng</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 24px; background: #f4f7f4; }}
            h1 {{ color: #1b5e20; }}
            table {{ width: 100%; border-collapse: collapse; background: #fff; }}
            th, td {{ border: 1px solid #d0d7d0; padding: 10px; vertical-align: top; text-align: left; }}
            th {{ background: #1b5e20; color: #fff; }}
            .btn-geo {{ display: inline-block; padding: 8px 14px; background: #2e7d32; color: #fff; text-decoration: none; border-radius: 6px; margin-bottom: 14px; }}
        </style>
    </head>
    <body>
        <h1>Trung tâm Tiếp nhận Tin báo Toàn dân Bảo vệ Rừng</h1>
        {sos_banner}
        <a class="btn-geo" href="/api/v1/reports.geojson" target="_blank">Tải lớp điểm GeoJSON (mở trên QGIS / MapInfo)</a>
        <table>
            <thead>
                <tr>
                    <th>Mã tin / Thời gian</th>
                    <th>Loại sự cố</th>
                    <th>Tọa độ VN-2000</th>
                    <th>Mô tả & Người báo</th>
                    <th>Ảnh hiện trường</th>
                    <th>Xử lý & Phản hồi</th>
                </tr>
            </thead>
            <tbody>{items_html or '<tr><td colspan="6">Chưa có tin báo nào.</td></tr>'}</tbody>
        </table>
        <h2 style="color:#1b5e20;margin-top:28px">Phê duyệt quyền Cán bộ Kiểm lâm (theo Mã thiết bị)</h2>
        <table>
            <thead><tr><th>Mã thiết bị</th><th>Họ tên & Đơn vị</th><th>SĐT</th><th>Trạng thái</th><th>Hành động</th></tr></thead>
            <tbody>{"".join(f"<tr><td>{o['device_id']}</td><td><b>{o['full_name']}</b><br><small>{o['unit_name']}</small></td><td>{o['phone']}</td><td><b>{'Đã phê duyệt' if o['status'] == 'APPROVED' else 'Chưa phê duyệt'}</b></td><td><form method='post' action='/api/v1/admin/officers/{o['device_id']}/decision' style='display:inline'><button name='action' value='APPROVE'>Phê duyệt</button> <button name='action' value='REVOKE'>Thu hồi</button></form></td></tr>" for o in officer_rows) or "<tr><td colspan='5'>Chưa có yêu cầu đăng ký cán bộ.</td></tr>"}</tbody>
        </table>
        <h2 style="color:#1b5e20;margin-top:28px">Cập nhật định kỳ bản đồ MBTiles (Hiện trạng / Quy hoạch / Tiểu khu)</h2>
        <form method="post" action="/api/v1/admin/map-layers" enctype="multipart/form-data" style="background:#fff;padding:14px;border:1px solid #d0d7d0;margin-bottom:12px">
            Mã lớp: <input name="layer_code" value="HTR_LAMDONG" required/>
            Tên hiển thị: <input name="title" value="Hiện trạng rừng Lâm Đồng" required/>
            Nhóm: <select name="category"><option value="HIEN_TRANG_RUNG">Hiện trạng rừng</option><option value="QUY_HOACH_LAM_NGHIEP">Quy hoạch lâm nghiệp</option><option value="RANH_GIOI_TIEU_KHU">Ranh giới tiểu khu</option></select>
            Phiên bản: <input name="version" value="v2026.11" required/>
            Quyền xem: <select name="access_level"><option value="RANGER_ONLY">Chỉ Cán bộ Kiểm lâm</option><option value="PUBLIC">Công khai toàn dân</option></select>
            Tệp .mbtiles: <input type="file" name="mbtiles_file" accept=".mbtiles" required/>
            <button type="submit">Tải lên & Phát hành OTA</button>
        </form>
        <table>
            <thead><tr><th>Mã lớp</th><th>Tên bản đồ</th><th>Nhóm</th><th>Phiên bản</th><th>Quyền xem</th><th>Dung lượng</th></tr></thead>
            <tbody>{"".join(f"<tr><td>{l['layer_code']}</td><td>{l['title']}</td><td>{l['category']}</td><td><b>{l['version']}</b></td><td>{l['access_level']}</td><td>{l['file_size_mb']} MB</td></tr>" for l in layer_rows) or "<tr><td colspan='6'>Chưa có lớp bản đồ nào.</td></tr>"}</tbody>
        </table>
        <h2 style="color:#bf360c;margin-top:28px">Đăng Điểm cảnh báo cháy rừng mới</h2>
        <form method="post" action="/api/v1/fire-alerts" style="background:#fff3e0;padding:14px;border:1px solid #ffcc80;margin-bottom:12px">
            Vị trí / Tiểu khu: <input name="location_name" value="Tiểu khu 144B - Đà Lạt" required/>
            Lat: <input name="latitude" value="11.9652" style="width:90px" required/>
            Lon: <input name="longitude" value="108.4810" style="width:90px" required/>
            VN2000 X(E): <input name="vn2000_y" value="579640.2" style="width:95px"/>
            VN2000 Y(N): <input name="vn2000_x" value="1323120.5" style="width:95px"/>
            Cấp/Tin cậy: <input name="confidence" value="Cấp IV - Nguy hiểm" style="width:130px"/>
            <button type="submit">Phát cảnh báo cháy</button>
        </form>
        <h2 style="color:#1b5e20;margin-top:28px">Cập nhật Thư viện Luật, Nghị định, Thông tư</h2>
        <form method="post" action="/api/v1/admin/legal-docs" enctype="multipart/form-data" style="background:#fff;padding:14px;border:1px solid #d0d7d0;margin-bottom:12px">
            Số hiệu: <input name="doc_symbol" placeholder="VD: 91/2024/NĐ-CP" required/>
            Loại: <select name="doc_type"><option>Luật</option><option selected>Nghị định</option><option>Thông tư</option><option>Quyết định</option></select>
            Tên văn bản: <input name="title" style="width:240px" required/><br><br>
            Tóm tắt: <input name="summary" style="width:320px"/>
            Link văn bản: <input name="doc_url" placeholder="https://..." style="width:200px"/>
            Hoặc tệp PDF/DOCX: <input type="file" name="doc_file"/>
            <button type="submit">Cập nhật lên Thư viện</button>
        </form>
        <h2 style="color:#1b5e20;margin-top:28px">Cập nhật Ảnh vệ tinh Basemap hàng tháng (GeoTIFF .tif / .tiff)</h2>
        <form method="post" action="/api/v1/admin/satellite-basemaps" enctype="multipart/form-data" style="background:#fff;padding:14px;border:1px solid #d0d7d0;margin-bottom:12px">
            Tên ảnh: <input name="title" value="Ảnh vệ tinh Basemap GeoTIFF Lâm Đồng" required/>
            Tháng: <select name="month"><option value="1">Tháng 1</option><option value="2">Tháng 2</option><option value="3">Tháng 3</option><option value="4">Tháng 4</option><option value="5">Tháng 5</option><option value="6">Tháng 6</option><option value="7">Tháng 7</option><option value="8">Tháng 8</option><option value="9">Tháng 9</option><option value="10">Tháng 10</option><option value="11" selected>Tháng 11</option><option value="12">Tháng 12</option></select>
            Năm: <input type="number" name="year" value="2026" min="2026" style="width:75px" required/><br><br>
            Tệp ảnh GeoTIFF (.tif / .tiff): <input type="file" name="geotiff_file" accept=".tif,.tiff"/>
            Link Tile XYZ (tùy chọn): <input name="tile_url" placeholder="https://.../z/x/y.png" style="width:200px"/><br><br>
            Khung tọa độ (nếu GeoTIFF chưa gắn WGS-84) — Bắc: <input name="north_lat" value="12.15" style="width:72px"/>
            Nam: <input name="south_lat" value="11.75" style="width:72px"/>
            Đông: <input name="east_lon" value="108.68" style="width:78px"/>
            Tây: <input name="west_lon" value="108.25" style="width:78px"/>
            <button type="submit">Phát hành Basemap GeoTIFF</button>
        </form>
    </body>
    </html>
    """
