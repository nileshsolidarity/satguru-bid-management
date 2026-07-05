"""
Satguru Bid Management — Flask server
Run: python3 server.py
Then open: http://localhost:3000
"""

import json
import os
import threading
import asyncio
from flask import Flask, send_from_directory, jsonify, request, Response
from flask_cors import CORS
from scraper import run_scraper

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GCS_BUCKET = "satguru-bid-tenders"
GCS_OBJECT = "tenders.json"
LOCAL_TENDERS = os.path.join(BASE_DIR, "tenders.json")

app = Flask(__name__, static_folder=BASE_DIR)
CORS(app, origins=["https://satguru-bid-management.vercel.app", "http://localhost:3000"])

scraper_status = {"running": False, "last_run": None, "last_count": 0, "error": None}


def is_cloud():
    return os.environ.get("K_SERVICE") is not None  # set by Cloud Run automatically


def read_tenders():
    if is_cloud():
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET)
            blob = bucket.blob(GCS_OBJECT)
            if blob.exists():
                return json.loads(blob.download_as_text())
        except Exception as e:
            print(f"GCS read error: {e}")
        return []
    else:
        if os.path.exists(LOCAL_TENDERS):
            with open(LOCAL_TENDERS) as f:
                return json.load(f)
        return []


def write_tenders(tenders):
    if is_cloud():
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET)
            blob = bucket.blob(GCS_OBJECT)
            blob.upload_from_string(json.dumps(tenders, indent=2), content_type="application/json")
            print(f"Saved {len(tenders)} tenders to GCS")
        except Exception as e:
            print(f"GCS write error: {e}")
    else:
        with open(LOCAL_TENDERS, "w") as f:
            json.dump(tenders, f, indent=2)
        print(f"Saved {len(tenders)} tenders locally")


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)


@app.route("/api/sync", methods=["POST"])
def sync():
    if scraper_status["running"]:
        return jsonify({"status": "already_running", "message": "Scraper is already running..."}), 200

    def run():
        scraper_status["running"] = True
        scraper_status["error"] = None
        try:
            results = asyncio.run(run_scraper(headless=True, save_fn=write_tenders, load_fn=read_tenders))
            scraper_status["last_count"] = len(results)
            scraper_status["last_run"] = __import__("datetime").datetime.now().isoformat()
        except Exception as e:
            scraper_status["error"] = str(e)
        finally:
            scraper_status["running"] = False

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return jsonify({"status": "started", "message": "Scraper started. Check back in 30-60 seconds."})


@app.route("/api/sync/status")
def sync_status():
    return jsonify(scraper_status)


@app.route("/api/tenders")
def get_tenders():
    return jsonify(read_tenders())


@app.route("/api/tender-detail")
def tender_detail():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400

    try:
        from scraper import fetch_tender_page
        html = asyncio.run(fetch_tender_page(url))
        return Response(html, mimetype="text/html")
    except Exception as e:
        return Response(f"<h2>Could not load tender</h2><p>{e}</p><p><a href='{url}' target='_blank'>Try opening directly</a></p>", mimetype="text/html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print(f"Satguru Bid Management running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
