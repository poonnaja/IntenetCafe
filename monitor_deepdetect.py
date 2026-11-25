import csv
import json
import os
import shutil
import time
import threading
from datetime import datetime
from pathlib import Path

import requests
import paho.mqtt.client as mqtt

HOST = '127.0.0.1'
PORT = 1883
TOPIC = 'internetcafe/table/01/status'
EQUIPMENT = ('Mouse', 'Keyboard', 'Headset', 'Controller')
WEBHOOK = os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
COOLDOWN = 10
LOG_INTERVAL = 30
STALE_AFTER = 30
CSV_PATH = Path(__file__).with_name('equipment_log.csv')
lock = threading.Lock()
last_signature = None
latest = None
pending = False
last_sent = None
last_received = None
revision = 0


def parse_payload(payload):
    obj = json.loads(payload.decode('utf-8-sig'))
    if not isinstance(obj, dict):
        raise ValueError('MQTT payload must be a JSON object')

    if isinstance(obj.get('detected'), dict):
        source = obj['detected']
    elif isinstance(obj.get('DeepDetect'), dict):
        deep = obj['DeepDetect']
        source = deep.get('counts', {})
        if not isinstance(source, dict):
            raise ValueError('DeepDetect.counts must be an object')
        # Some CiRA versions provide counts only in the objects list.
        if not source and isinstance(deep.get('objects'), list):
            derived = {}
            for item in deep['objects']:
                if not isinstance(item, dict):
                    continue
                label = next((item.get(k) for k in ('name', 'label', 'class_name', 'class')
                              if isinstance(item.get(k), str)), None)
                if label:
                    derived[label] = derived.get(label, 0) + 1
            source = derived
    else:
        raise ValueError('Expected detected or DeepDetect object')

    detected = {name: 0 for name in EQUIPMENT}
    for label, value in source.items():
        name = next((n for n in EQUIPMENT if str(label).strip().casefold() == n.casefold()), None)
        if name is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f'Invalid count for {name}: {value!r}')
        detected[name] += int(value)

    return {'table_id': str(obj.get('table_id', 'TABLE-01')),
            'detected': detected,
            'missing': [name for name in EQUIPMENT if detected[name] == 0],
            'status': 'COMPLETE' if all(detected.values()) else 'INCOMPLETE'}


CSV_HEADERS = [
    'วันที่', 'เวลา', 'รหัสโต๊ะ', *EQUIPMENT,
    'จำนวนที่พบ', 'สถานะ', 'อุปกรณ์ที่ไม่พบ'
]


def save_csv(data, stale=False):
    if CSV_PATH.exists() and CSV_PATH.stat().st_size:
        with CSV_PATH.open('r', encoding='utf-8-sig', newline='') as existing:
            header = next(csv.reader(existing), [])
        if header != CSV_HEADERS:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup = CSV_PATH.with_name(f'equipment_log_backup_{stamp}.csv')
            number = 1
            while backup.exists():
                backup = CSV_PATH.with_name(f'equipment_log_backup_{stamp}_{number}.csv')
                number += 1
            shutil.move(str(CSV_PATH), str(backup))
            print('Previous CSV backed up:', backup, flush=True)
    first = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    now = datetime.now()
    counts = data['detected']
    missing = [name for name in EQUIPMENT if counts[name] == 0]
    row = [now.strftime('%d/%m/%Y'), now.strftime('%H:%M:%S'), data['table_id']]
    if stale:
        row += ['ไม่ทราบ'] * 4 + ['-', 'ไม่มีข้อมูลล่าสุด', 'ไม่ทราบ']
    else:
        row += ['พบ' if counts[name] > 0 else 'ไม่พบ' for name in EQUIPMENT]
        row += [f'{4-len(missing)}/4', 'ครบ' if not missing else 'ไม่ครบ',
                ', '.join(missing) if missing else 'ไม่มี']
    with CSV_PATH.open('a', encoding='utf-8-sig' if first else 'utf-8', newline='') as file:
        writer = csv.writer(file)
        if first:
            writer.writerow(CSV_HEADERS)
        writer.writerow(row)
    print('CSV saved:', row[1], '|', row[-2], '| missing:', row[-1], flush=True)


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
        print('Discord error:', type(exc).__name__, flush=True)
        return False


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe(TOPIC)
        print('MQTT connected; subscribed:', TOPIC, flush=True)
    else:
        print('MQTT connect failed:', reason_code, flush=True)


def on_message(client, userdata, msg):
    global last_signature, latest, pending, last_received, revision
    try:
        data = parse_payload(msg.payload)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print('Invalid MQTT data:', exc, 'Payload sample:', repr(msg.payload[:250]), flush=True)
        return
    signature = tuple(data['detected'][name] > 0 for name in EQUIPMENT)
    with lock:
        latest = data
        last_received = time.monotonic()
        if signature == last_signature:
            return
        initial = last_signature is None
        last_signature = signature
        revision += 1
        if not initial:
            pending = True
    if initial:
        print('Initial baseline received; Discord notification starts on next change', flush=True)
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
    next_log = None
    next_attempt = 0
    print('CSV interval:', LOG_INTERVAL, 'seconds', flush=True)
    try:
        while True:
            now = time.monotonic()
            with lock:
                current = latest
                stale = last_received is None or now - last_received >= STALE_AFTER
                ready = pending and current is not None and not stale and now >= next_attempt and (last_sent is None or now - last_sent >= COOLDOWN)
                snapshot = current if ready else None
                sent_revision = revision
            if current is not None and (next_log is None or now >= next_log):
                try:
                    save_csv(current, stale)
                    next_log = now + LOG_INTERVAL
                except OSError as exc:
                    print('CSV write failed:', type(exc).__name__, flush=True)
                    next_log = now + 5
            if snapshot is not None:
                success = send_discord(snapshot)
                next_attempt = time.monotonic() + COOLDOWN
                if success:
                    with lock:
                        last_sent = time.monotonic()
                        if revision == sent_revision:
                            pending = False
            time.sleep(1)
    except KeyboardInterrupt:
        print('Stopping...', flush=True)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    main()
