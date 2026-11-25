import csv
import json
import os
import time
import threading
from datetime import datetime
from pathlib import Path

import requests
import paho.mqtt.client as mqtt

HOST = '127.0.0.1'
PORT = 1883
TOPIC = 'internetcafe/table/01/status'
EQUIPMENT = ('Keyboard', 'Mouse', 'Headset', 'Controller')
WEBHOOK = os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
COOLDOWN = 30 * 60
CSV_PATH = Path(__file__).with_name('equipment_log.csv')
lock = threading.Lock()
last_signature = None
latest = None
pending = False
last_sent = None


def parse_payload(payload):
    obj = json.loads(payload.decode('utf-8-sig'))
    if not isinstance(obj, dict) or not isinstance(obj.get('detected'), dict):
        raise ValueError('Expected JSON with detected object')
    detected = {}
    for name in EQUIPMENT:
        value = obj['detected'].get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f'detected.{name} must be a nonnegative integer')
        detected[name] = value
    return {'table_id': str(obj.get('table_id', 'TABLE-01')),
            'detected': detected,
            'missing': [name for name in EQUIPMENT if detected[name] == 0],
            'status': 'COMPLETE' if all(detected.values()) else 'INCOMPLETE'}


def save_csv(data):
    first = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    with CSV_PATH.open('a', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        if first:
            writer.writerow(['timestamp', 'table_id', 'status', *EQUIPMENT, 'missing'])
        writer.writerow([datetime.now().isoformat(timespec='seconds'), data['table_id'],
                         data['status'], *(data['detected'][name] for name in EQUIPMENT),
                         ', '.join(data['missing'])])
    print('CSV saved:', data['status'], 'missing:', data['missing'], flush=True)


def send_discord(data):
    if not WEBHOOK:
        print('Discord webhook missing: set DISCORD_WEBHOOK_URL before running', flush=True)
        return False
    present = [name for name in EQUIPMENT if data['detected'][name] > 0]
    missing = data['missing']
    message = ('📢 **รายงานสถานะอุปกรณ์**\n'
               f"โต๊ะ: {data['table_id']}\n\n"
               '🟢 **อุปกรณ์ที่ตรวจพบ**\n' +
               ('\n'.join('✅ ' + name for name in present) or 'ไม่มี') + '\n\n'
               '🔴 **อุปกรณ์ที่ไม่พบ**\n' +
               ('\n'.join('❌ ' + name for name in missing) or 'ไม่มี') + '\n\n'
               f"สถานะรวม: **{data['status']}**")
    try:
        response = requests.post(WEBHOOK, json={'content': message}, timeout=10)
        response.raise_for_status()
        print('Discord notification sent:', response.status_code, flush=True)
        return True
    except requests.RequestException as exc:
        print('Discord error:', exc, flush=True)
        return False


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe(TOPIC)
        print('MQTT connected; subscribed:', TOPIC, flush=True)
    else:
        print('MQTT connect failed:', reason_code, flush=True)


def on_message(client, userdata, msg):
    global last_signature, latest, pending
    try:
        data = parse_payload(msg.payload)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print('Invalid MQTT data:', exc, 'Payload sample:', repr(msg.payload[:250]), flush=True)
        return
    signature = tuple(data['detected'][name] > 0 for name in EQUIPMENT)
    with lock:
        if signature == last_signature:
            return
        initial = last_signature is None
        last_signature = signature
        latest = data
        if not initial:
            pending = True
    save_csv(data)
    if initial:
        print('Initial baseline saved; Discord notification starts on next change', flush=True)
    else:
        print('Equipment status changed; Discord notification queued', flush=True)


def main():
    global pending, last_sent
    print('Internet Cafe Monitor Started', flush=True)
    print('Discord cooldown:', COOLDOWN, 'seconds', flush=True)
    print('CSV:', CSV_PATH, flush=True)
    if not WEBHOOK:
        print('WARNING: DISCORD_WEBHOOK_URL is not set', flush=True)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    print('Connecting to Mosquitto...', flush=True)
    client.connect(HOST, PORT, 60)
    client.loop_start()
    try:
        while True:
            with lock:
                ready = pending and latest is not None and (last_sent is None or time.monotonic() - last_sent >= COOLDOWN)
                snapshot = latest.copy() if ready else None
            if snapshot is not None:
                success = send_discord(snapshot)
                if success:
                    with lock:
                        last_sent = time.monotonic()
                        if latest == snapshot:
                            pending = False
            time.sleep(1)
    except KeyboardInterrupt:
        print('Stopping...', flush=True)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
