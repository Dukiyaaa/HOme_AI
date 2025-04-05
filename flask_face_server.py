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

# === AI 聊天接口 ===
@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({'error': 'Missing message'}), 400

    user_input = data['message']

    # ✅ 你可以根据需要替换 system prompt 内容
    system_prompt = (
        "你是智能家居助手，请根据设备状态给出实用建议，语气自然真实，回答尽量简短。"
    )

    payload = {
        "model": "deepseek-chat",  # 或 deepseek-coder
        "messages": [
            {"role": "system", "content": system_prompt},
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
        print("🔍 Token 用量：", usage)

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
from datetime import datetime  # ✅ 你漏掉了这一行
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

        # 字段分类识别
        sensor_keys = {
            "temperature_indoor", "humidity_indoor", "smoke", "comb",
            "light", "current", "voltage", "power"
        }
        home_keys = {
            "door_state", "airConditioner_state", "curtain_percent", "led_lightness_color"
        }

        sensor_data = {k: v for k, v in props.items() if k in sensor_keys}
        home_data = {k: v for k, v in props.items() if k in home_keys}

        if sensor_data:
            cache_data[device_id]['sensor'] = sensor_data
        if home_data:
            cache_data[device_id]['home'] = home_data

        print(f"🔄 当前缓存: {cache_data[device_id]}", flush=True)

        # ✅ 合并条件满足时写入数据库
        if 'sensor' in cache_data[device_id] and 'home' in cache_data[device_id]:
            merged = {**cache_data[device_id]['sensor'], **cache_data[device_id]['home']}
            print(f"✅ 数据合并并写入数据库: {merged}", flush=True)

            keys = list(merged.keys())
            values = [merged[k] for k in keys]
            columns = ', '.join(keys + ['created_at'])
            placeholders = ', '.join(['%s'] * len(keys) + ['%s'])
            values.append(datetime.now())

            sql = f"INSERT INTO device_data ({columns}) VALUES ({placeholders})"

            # 执行数据库写入
            try:
                conn = pymysql.connect(**db_config)
                with conn.cursor() as cursor:
                    cursor.execute(sql, values)
                conn.commit()
                conn.close()
            except Exception as db_error:
                print("❌ 写入数据库失败:", db_error, flush=True)
                return jsonify({'error': str(db_error)}), 500

            # 清除缓存
            del cache_data[device_id]

            return jsonify({'status': 'success', 'inserted': keys})

        # 等待另一类数据
        return jsonify({
            'status': 'waiting',
            'cached_keys': list(cache_data[device_id].keys())
        })

    except Exception as e:
        print("❌ 接口异常:", e, flush=True)
        return jsonify({'error': str(e)}), 500

# === 数据库增删改查接口 ===

# === 启动 Flask 应用 ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
