
from flask import Flask, request, jsonify
import face_recognition
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
KNOWN_FACES_DIR = 'known_faces'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)

# Load known faces
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
