from flask import Flask, request, jsonify
import face_recognition
import os
from werkzeug.utils import secure_filename
import requests as req
from dotenv import load_dotenv

# === 环境初始化 ===
app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
KNOWN_FACES_DIR = 'known_faces'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)

# === 加载已知人脸 ===
known_face_encodings = []
known_face_names = []

for filename in os.listdir(KNOWN_FACES_DIR):
    if filename.endswith(('.jpg', '.png')):
        path = os.path.join(KNOWN_FACES_DIR, filename)
        image = face_recognition.load_image_file(path)
        encodings = face_recognition.face_encodings(image)
        if encodings:
            known_face_encodings.append(encodings[0])
            known_face_names.append(os.path.splitext(filename)[0])
        else:
            print(f"No face found in {filename}, skipped.")

# === 上传识别人脸接口 ===
@app.route('/upload_photo', methods=['POST'])
def upload_photo():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    image = face_recognition.load_image_file(filepath)
    locations = face_recognition.face_locations(image)
    encodings = face_recognition.face_encodings(image, locations)

    results = []
    for encoding, location in zip(encodings, locations):
        matches = face_recognition.compare_faces(known_face_encodings, encoding)
        name = "Unknown"
        if True in matches:
            name = known_face_names[matches.index(True)]
        results.append({'name': name, 'location': location})

    return jsonify({'faces_detected': len(results), 'results': results})

# === 加载环境变量 ===
load_dotenv()
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
print("当前 API Key 为:", DEEPSEEK_API_KEY)


# 加载标志
pretrained_prompt_loaded = False
PRETRAINED_SYSTEM_PROMPT = "你是智能家居助手，请根据设备状态给出实用建议。"

def load_pretrained_prompt_if_needed():
    global pretrained_prompt_loaded, PRETRAINED_SYSTEM_PROMPT
    if pretrained_prompt_loaded:
        return

    try:
        print("🧠 正在首次加载家居数据（仅一次）...")
        res = req.get("http://localhost:5000/data/export", timeout=5)
        if res.status_code == 200:
            lines = res.text.strip().splitlines()
            csv_sample = '\n'.join(lines[:10])
            PRETRAINED_SYSTEM_PROMPT = (
                "你是一个智能家居助手，以下是最近收集的设备状态数据（用于理解，不对用户展示）：\n\n"
                f"{csv_sample}\n\n"
                "你已经掌握这些数据，请根据它们回答用户问题。"
            )
            pretrained_prompt_loaded = True
            print("✅ Prompt 加载完成。")
    except Exception as e:
        print("⚠️ Prompt 加载失败：", e)


# === AI 聊天接口 ===
@app.route('/chat', methods=['POST'])
def chat():
    load_pretrained_prompt_if_needed()
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({'error': 'Missing message'}), 400

    user_input = data['message']

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": PRETRAINED_SYSTEM_PROMPT},
            {"role": "user", "content": user_input}
        ],
        "temperature": 0.7
    }

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = req.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        ai_reply = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return jsonify({'reply': ai_reply, 'usage': usage})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

import pymysql

# === MySQL 配置 ===
db_config = {
    'host': 'localhost',
    'user': 'flaskuser',
    'password': '123456',
    'database': 'home_database',
    'port': 3306,
    'charset': 'utf8mb4'
}

# 全局缓存：按 device_id 缓存未合并数据
cache_data = {}
from datetime import datetime
import csv
import os

# 导出阈值设置
MAX_ROWS = 10000
ARCHIVE_FOLDER = 'data_archives'
os.makedirs(ARCHIVE_FOLDER, exist_ok=True)

def export_and_clear_device_data():
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM device_data")
            row_count = cursor.fetchone()["total"]
            if row_count < MAX_ROWS:
                return

            print(f"⚠️ 数据量达到 {row_count} 条，导出 CSV 并清空！", flush=True)

            cursor.execute("SELECT * FROM device_data ORDER BY created_at ASC")
            rows = cursor.fetchall()

            if rows:
                now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"device_data_backup_{now_str}.csv"
                full_path = os.path.join(ARCHIVE_FOLDER, filename)

                with open(full_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)

                print(f"✅ 已备份至 {full_path}", flush=True)

            cursor.execute("TRUNCATE TABLE device_data")
            conn.commit()
            print("✅ 已清空 device_data 表", flush=True)

        conn.close()
    except Exception as e:
        print("❌ 导出并清空失败：", e, flush=True)


@app.route('/iot-data', methods=['POST'])
def receive_iot_data():
    try:
        data = request.get_json()
        print("📦 接收到设备数据:", data, flush=True)

        notify = data.get('notify_data', {})
        device_id = notify.get('header', {}).get('device_id', 'unknown_device')
        services = notify.get('body', {}).get('services', [])

        if not device_id or not services:
            return jsonify({'error': 'Missing device_id or services'}), 400

        service = services[0]
        props = service.get('properties', {})
        if not props:
            return jsonify({'error': 'Missing properties'}), 400

        # 初始化缓存结构
        if device_id not in cache_data:
            cache_data[device_id] = {}

        sensor_keys = {
            "temperature_indoor", "humidity_indoor", "smoke", "comb",
            "light", "current", "voltage", "power", "sr501_state", "beep_state"
        }
        home_keys = {
            "door_state", "airConditioner_state", "curtain_percent", "led_lightness_color", "automation_mode_scene"
        }

        sensor_data = {k: v for k, v in props.items() if k in sensor_keys}
        home_data = {k: v for k, v in props.items() if k in home_keys}

        if sensor_data:
            cache_data[device_id]['sensor'] = sensor_data
        if home_data:
            cache_data[device_id]['home'] = home_data

        print(f"🔄 当前缓存: {cache_data[device_id]}", flush=True)

        if 'sensor' in cache_data[device_id] and 'home' in cache_data[device_id]:
            merged = {**cache_data[device_id]['sensor'], **cache_data[device_id]['home']}
            print(f"✅ 数据合并并写入数据库: {merged}", flush=True)

            keys = list(merged.keys())
            values = [merged[k] for k in keys]
            columns = ', '.join(keys + ['created_at'])
            placeholders = ', '.join(['%s'] * len(keys) + ['%s'])
            values.append(datetime.now())

            sql = f"INSERT INTO device_data ({columns}) VALUES ({placeholders})"

            try:
                conn = pymysql.connect(**db_config)
                with conn.cursor() as cursor:
                    cursor.execute(sql, values)
                conn.commit()
                conn.close()

                # ✅ 插入后触发导出+清空
                export_and_clear_device_data()

            except Exception as db_error:
                print("❌ 写入数据库失败:", db_error, flush=True)
                return jsonify({'error': str(db_error)}), 500

            del cache_data[device_id]
            return jsonify({'status': 'success', 'inserted': keys})

        return jsonify({
            'status': 'waiting',
            'cached_keys': list(cache_data[device_id].keys())
        })

    except Exception as e:
        print("❌ 接口异常:", e, flush=True)
        return jsonify({'error': str(e)}), 500


# === 数据库增删改查接口 ===
@app.route('/data', methods=['POST'])
def insert_data():
    try:
        payload = request.get_json()
        keys = list(payload.keys())
        values = [payload[k] for k in keys]

        placeholders = ', '.join(['%s'] * len(keys))
        columns = ', '.join(keys)

        sql = f"INSERT INTO device_data ({columns}) VALUES ({placeholders})"

        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()

        return jsonify({'status': 'inserted', 'fields': keys}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/data', methods=['GET'])
def get_all_data():
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM device_data ORDER BY created_at DESC")
            rows = cursor.fetchall()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/data/<int:id>', methods=['GET'])
def get_data_by_id(id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM device_data WHERE device_data_id=%s", (id,))
            row = cursor.fetchone()
        conn.close()
        if row:
            return jsonify(row)
        else:
            return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/data/<int:id>', methods=['PUT'])
def update_data(id):
    try:
        payload = request.get_json()
        updates = ', '.join([f"{k}=%s" for k in payload])
        values = list(payload.values())
        values.append(id)

        sql = f"UPDATE device_data SET {updates} WHERE device_data_id=%s"

        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()

        return jsonify({'status': 'updated', 'id': id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/data/<int:id>', methods=['DELETE'])
def delete_data(id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM device_data WHERE device_data_id=%s", (id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'deleted', 'id': id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/data/latest', methods=['GET'])
def get_latest_data():
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM device_data 
                ORDER BY created_at DESC 
                LIMIT 1
            """)
            row = cursor.fetchone()
        conn.close()
        if row:
            return jsonify({'status': 'success', 'latest': row})
        else:
            return jsonify({'status': 'empty', 'message': 'No data found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

import csv
from io import StringIO
from flask import Response

@app.route('/data/export', methods=['GET'])
def export_data_as_csv():
    try:
        # 连接数据库并取最近100条数据
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM device_data 
                ORDER BY created_at DESC 
                LIMIT 100
            """)
            rows = cursor.fetchall()
        conn.close()

        if not rows:
            return jsonify({'error': 'No data to export'}), 404

        # 创建 CSV 字符流
        si = StringIO()
        writer = csv.DictWriter(si, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

        output = si.getvalue()
        si.close()

        # 返回 CSV 文件流
        return Response(
            output,
            mimetype='text/csv',
            headers={
                "Content-Disposition": "attachment; filename=latest_100_device_data.csv"
            }
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === device 表 CRUD 接口 ===

@app.route('/device', methods=['POST'])
def insert_device():
    try:
        payload = request.get_json()
        keys = list(payload.keys())
        values = [payload[k] for k in keys]

        placeholders = ', '.join(['%s'] * len(keys))
        columns = ', '.join(keys)
        sql = f"INSERT INTO device ({columns}) VALUES ({placeholders})"

        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'inserted', 'fields': keys}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/device', methods=['GET'])
def get_all_device():
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM device")
            rows = cursor.fetchall()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/device/<device_id>', methods=['GET'])
def get_device_by_id(device_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM device WHERE device_id=%s", (device_id,))
            row = cursor.fetchone()
        conn.close()
        return jsonify(row if row else {'error': 'Not found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/device/<device_id>', methods=['PUT'])
def update_device(device_id):
    try:
        payload = request.get_json()
        updates = ', '.join([f"{k}=%s" for k in payload])
        values = list(payload.values())
        values.append(device_id)

        sql = f"UPDATE device SET {updates} WHERE device_id=%s"
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'updated', 'device_id': device_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/device/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM device WHERE device_id=%s", (device_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'deleted', 'device_id': device_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === command_log 表 CRUD 接口 ===

@app.route('/command_log', methods=['POST'])
def insert_command_log():
    try:
        payload = request.get_json()
        keys = list(payload.keys())
        values = [payload[k] for k in keys]

        placeholders = ', '.join(['%s'] * len(keys))
        columns = ', '.join(keys)
        sql = f"INSERT INTO command_log ({columns}) VALUES ({placeholders})"

        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'inserted', 'fields': keys}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/command_log', methods=['GET'])
def get_all_command_log():
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM command_log")
            rows = cursor.fetchall()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/command_log/<int:command_log_id>', methods=['GET'])
def get_command_log_by_id(command_log_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM command_log WHERE command_log_id=%s", (command_log_id,))
            row = cursor.fetchone()
        conn.close()
        return jsonify(row if row else {'error': 'Not found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/command_log/<int:command_log_id>', methods=['PUT'])
def update_command_log(command_log_id):
    try:
        payload = request.get_json()
        updates = ', '.join([f"{k}=%s" for k in payload])
        values = list(payload.values())
        values.append(command_log_id)

        sql = f"UPDATE command_log SET {updates} WHERE command_log_id=%s"
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'updated', 'command_log_id': command_log_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/command_log/<int:command_log_id>', methods=['DELETE'])
def delete_command_log(command_log_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM command_log WHERE command_log_id=%s", (command_log_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'deleted', 'command_log_id': command_log_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === alarm_event 表 CRUD 接口 ===

@app.route('/alarm_event', methods=['POST'])
def insert_alarm_event():
    try:
        payload = request.get_json()
        keys = list(payload.keys())
        values = [payload[k] for k in keys]

        placeholders = ', '.join(['%s'] * len(keys))
        columns = ', '.join(keys)
        sql = f"INSERT INTO alarm_event ({columns}) VALUES ({placeholders})"

        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'inserted', 'fields': keys}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/alarm_event', methods=['GET'])
def get_all_alarm_event():
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM alarm_event")
            rows = cursor.fetchall()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/alarm_event/<int:alarm_event_id>', methods=['GET'])
def get_alarm_event_by_id(alarm_event_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM alarm_event WHERE alarm_event_id=%s", (alarm_event_id,))
            row = cursor.fetchone()
        conn.close()
        return jsonify(row if row else {'error': 'Not found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/alarm_event/<int:alarm_event_id>', methods=['PUT'])
def update_alarm_event(alarm_event_id):
    try:
        payload = request.get_json()
        updates = ', '.join([f"{k}=%s" for k in payload])
        values = list(payload.values())
        values.append(alarm_event_id)

        sql = f"UPDATE alarm_event SET {updates} WHERE alarm_event_id=%s"
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'updated', 'alarm_event_id': alarm_event_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/alarm_event/<int:alarm_event_id>', methods=['DELETE'])
def delete_alarm_event(alarm_event_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM alarm_event WHERE alarm_event_id=%s", (alarm_event_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'deleted', 'alarm_event_id': alarm_event_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === face_whitelist 表 CRUD 接口 ===

@app.route('/face_whitelist', methods=['POST'])
def insert_face_whitelist():
    try:
        payload = request.get_json()
        keys = list(payload.keys())
        values = [payload[k] for k in keys]

        placeholders = ', '.join(['%s'] * len(keys))
        columns = ', '.join(keys)
        sql = f"INSERT INTO face_whitelist ({columns}) VALUES ({placeholders})"

        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'inserted', 'fields': keys}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/face_whitelist', methods=['GET'])
def get_all_face_whitelist():
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM face_whitelist")
            rows = cursor.fetchall()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/face_whitelist/<int:face_whitelist_id>', methods=['GET'])
def get_face_whitelist_by_id(face_whitelist_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM face_whitelist WHERE face_whitelist_id=%s", (face_whitelist_id,))
            row = cursor.fetchone()
        conn.close()
        return jsonify(row if row else {'error': 'Not found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/face_whitelist/<int:face_whitelist_id>', methods=['PUT'])
def update_face_whitelist(face_whitelist_id):
    try:
        payload = request.get_json()
        updates = ', '.join([f"{k}=%s" for k in payload])
        values = list(payload.values())
        values.append(face_whitelist_id)

        sql = f"UPDATE face_whitelist SET {updates} WHERE face_whitelist_id=%s"
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'updated', 'face_whitelist_id': face_whitelist_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/face_whitelist/<int:face_whitelist_id>', methods=['DELETE'])
def delete_face_whitelist(face_whitelist_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM face_whitelist WHERE face_whitelist_id=%s", (face_whitelist_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'deleted', 'face_whitelist_id': face_whitelist_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === emergency_contact 表 CRUD 接口 ===

@app.route('/emergency_contact', methods=['POST'])
def insert_emergency_contact():
    try:
        payload = request.get_json()
        keys = list(payload.keys())
        values = [payload[k] for k in keys]

        placeholders = ', '.join(['%s'] * len(keys))
        columns = ', '.join(keys)
        sql = f"INSERT INTO emergency_contact ({columns}) VALUES ({placeholders})"

        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'inserted', 'fields': keys}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/emergency_contact', methods=['GET'])
def get_all_emergency_contact():
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM emergency_contact")
            rows = cursor.fetchall()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/emergency_contact/<int:emergency_contact_id>', methods=['GET'])
def get_emergency_contact_by_id(emergency_contact_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM emergency_contact WHERE emergency_contact_id=%s", (emergency_contact_id,))
            row = cursor.fetchone()
        conn.close()
        return jsonify(row if row else {'error': 'Not found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/emergency_contact/<int:emergency_contact_id>', methods=['PUT'])
def update_emergency_contact(emergency_contact_id):
    try:
        payload = request.get_json()
        updates = ', '.join([f"{k}=%s" for k in payload])
        values = list(payload.values())
        values.append(emergency_contact_id)

        sql = f"UPDATE emergency_contact SET {updates} WHERE emergency_contact_id=%s"
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
        conn.close()
        return jsonify({'status': 'updated', 'emergency_contact_id': emergency_contact_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/emergency_contact/<int:emergency_contact_id>', methods=['DELETE'])
def delete_emergency_contact(emergency_contact_id):
    try:
        conn = pymysql.connect(**db_config)
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM emergency_contact WHERE emergency_contact_id=%s", (emergency_contact_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'deleted', 'emergency_contact_id': emergency_contact_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === 启动 Flask 应用 ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
