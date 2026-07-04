"""
Satguru Bid Management — Flask server
Run: python3 server.py
Then open: http://localhost:3000
"""

import json
import os
import threading
import asyncio
from flask import Flask, send_from_directory, jsonify
from scraper import run_scraper

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR)

scraper_status = {"running": False, "last_run": None, "last_count": 0, "error": None}


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
            results = asyncio.run(run_scraper(headless=True))
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
    tenders_file = os.path.join(BASE_DIR, "tenders.json")
    if not os.path.exists(tenders_file):
        return jsonify([])
    with open(tenders_file) as f:
        return jsonify(json.load(f))


if __name__ == "__main__":
    print("Satguru Bid Management running at http://localhost:3000")
    app.run(port=3000, debug=False)
