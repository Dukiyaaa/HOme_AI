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

@app.route('/iot-data', methods=['POST'])
def receive_iot_data():
    try:
        print("📥 Headers:", dict(request.headers), flush=True)
        data = request.get_json()
        print("📦 接收到设备数据:", data, flush=True)

        # ✅ 修复这里：深入嵌套结构取 services
        services = data.get('notify_data', {}).get('body', {}).get('services', [])
        if not services:
            return jsonify({'error': 'No service data'}), 400

        props = services[0].get('properties', {})
        keys = list(props.keys())
        values = [props.get(k, None) for k in keys]

        placeholders = ', '.join(['%s'] * len(keys))
        columns = ', '.join(keys)
        sql = f"INSERT INTO device_data ({columns}) VALUES ({placeholders})"

        # 插入数据库
        connection = pymysql.connect(**db_config)
        with connection.cursor() as cursor:
            cursor.execute(sql, values)
        connection.commit()
        connection.close()

        return jsonify({'status': 'success', 'inserted': keys})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === 启动 Flask 应用 ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
