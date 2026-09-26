#!/usr/bin/env python3

import json
import os
from pathlib import Path
from flask import Flask, Response, request, jsonify

app = Flask(__name__)

config = {}

CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.txt': 'text/plain; charset=utf-8',
    '.xml': 'application/xml; charset=utf-8',
    '.zip': 'application/zip',
    '.pdf': 'application/pdf',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
}


def load_config():
    global config
    config_file = Path(__file__).parent / "config.json"

    if not config_file.exists():
        print(f"Warning: {config_file} not found, using defaults")
        config = {
            "server": {"host": "0.0.0.0", "port": 8000},
            "data": {"path": "./data"}
        }
        return

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    print(f"Loaded config from {config_file}")


def get_data_dir():
    data_path = config.get("data", {}).get("path", "./data")
    return Path(__file__).parent / data_path


def get_content_type(filename):
    ext = Path(filename).suffix.lower()
    return CONTENT_TYPES.get(ext, 'application/octet-stream')


def find_file(filename):
    data_dir = get_data_dir()

    exact_path = data_dir / filename
    if exact_path.exists() and exact_path.is_file():
        return exact_path

    for ext in CONTENT_TYPES.keys():
        file_path = data_dir / f"{filename}{ext}"
        if file_path.exists() and file_path.is_file():
            return file_path

    return None


@app.route('/content/<filename>')
def serve_content(filename):
    data_dir = get_data_dir()

    file_path = find_file(filename)

    if file_path is None:
        return jsonify({
            "error": "Not Found",
            "message": f"File not found: {filename}"
        }), 404

    try:
        file_path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return jsonify({
            "error": "Forbidden",
            "message": "Access denied"
        }), 403

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    content_type = get_content_type(file_path.name)

    return Response(content, mimetype=content_type)


@app.route('/__list', methods=['GET'])
def list_files():
    data_dir = get_data_dir()

    if not data_dir.exists():
        return jsonify({"count": 0, "files": []})

    files = []
    for f in data_dir.iterdir():
        if f.is_file():
            files.append(f.name)

    return jsonify({
        "count": len(files),
        "files": sorted(files)
    })


@app.route('/__reload', methods=['POST'])
def reload_config():
    load_config()
    return jsonify({"status": "ok", "message": "Configuration reloaded"})


@app.route('/download/<path:filename>')
def download_file(filename):
    data_dir = get_data_dir()

    if '..' in filename:
        return jsonify({
            "error": "Forbidden",
            "message": "Invalid filename"
        }), 403

    file_path = data_dir / filename

    if not file_path.exists() or not file_path.is_file():
        return jsonify({
            "error": "Not Found",
            "message": f"File not found: {filename}"
        }), 404

    try:
        file_path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return jsonify({
            "error": "Forbidden",
            "message": "Access denied"
        }), 403

    content_type = get_content_type(file_path.name)

    with open(file_path, 'rb') as f:
        content = f.read()

    response = Response(content, mimetype=content_type)
    response.headers['Content-Disposition'] = f'attachment; filename="{file_path.name}"'
    return response


@app.route('/site/<path:filepath>')
def serve_site(filepath):
    data_dir = get_data_dir()

    if '..' in filepath:
        return jsonify({
            "error": "Forbidden",
            "message": "Invalid path"
        }), 403

    file_path = data_dir / filepath

    if not file_path.exists() or not file_path.is_file():
        return jsonify({
            "error": "Not Found",
            "message": f"File not found: {filepath}"
        }), 404

    try:
        file_path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return jsonify({
            "error": "Forbidden",
            "message": "Access denied"
        }), 403

    content_type = get_content_type(file_path.name)

    with open(file_path, 'rb') as f:
        content = f.read()

    return Response(content, mimetype=content_type)


@app.route('/upload', methods=['POST'])
def upload_file():
    data_dir = get_data_dir()

    data_dir.mkdir(parents=True, exist_ok=True)

    if 'file' not in request.files:
        return jsonify({
            "error": "Bad Request",
            "message": "No file provided. Use 'file' field in multipart form."
        }), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({
            "error": "Bad Request",
            "message": "No file selected"
        }), 400

    filename = file.filename

    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({
            "error": "Forbidden",
            "message": "Invalid filename"
        }), 403

    save_path = data_dir / filename
    file.save(save_path)

    file_size = save_path.stat().st_size

    return jsonify({
        "status": "ok",
        "message": "File uploaded successfully",
        "file": {
            "name": filename,
            "size": file_size,
            "path": f"/content/{filename}"
        }
    })


@app.route('/')
def root():
    return jsonify({
        "service": "Mock API",
        "version": "2.2.0",
        "status": "running",
        "endpoints": {
            "/content/<filename>": "Serve file from data directory (without extension)",
            "/download/<filename>": "Download file by exact filename (with extension)",
            "/site/<path>": "Serve file with full path support (for website testing)",
            "/__list": "List available files",
            "/__reload": "Reload configuration",
            "/upload": "Upload a file (POST multipart/form-data)"
        }
    })


if __name__ == '__main__':
    load_config()

    host = config.get("server", {}).get("host", "0.0.0.0")
    port = config.get("server", {}).get("port", 8000)

    data_dir = get_data_dir()
    print(f"\nMock API Server starting on {host}:{port}")
    print(f"Data directory: {data_dir}")
    print(f"Available endpoints:")
    print(f"  - GET /content/<filename> : Serve file (without extension)")
    print(f"  - GET /download/<filename>: Download file (exact filename)")
    print(f"  - GET /site/<path>        : Serve file with full path (website)")
    print(f"  - GET /__list             : List available files")
    print(f"  - POST /__reload          : Reload configuration")
    print(f"  - POST /upload            : Upload a file\n")

    app.run(host=host, port=port, debug=False)