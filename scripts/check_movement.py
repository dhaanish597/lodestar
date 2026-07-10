import json

with open("ws_output.log", "r", encoding="utf-16le") as f:
    lines = f.readlines()

mmsi_positions = {}
for line in lines:
    if line.startswith("[") and "Received:" in line:
        try:
            data_str = line.split("Received: ")[1].strip()
            vessels = json.loads(data_str)
            for v in vessels:
                mmsi = v["mmsi"]
                pos = (v["lat"], v["lon"], v["timestamp"])
                if mmsi not in mmsi_positions:
                    mmsi_positions[mmsi] = []
                # Only add if position is different from last one
                if not mmsi_positions[mmsi] or (mmsi_positions[mmsi][-1][0] != pos[0] or mmsi_positions[mmsi][-1][1] != pos[1]):
                    mmsi_positions[mmsi].append(pos)
        except Exception as e:
            pass

for mmsi, pos_list in mmsi_positions.items():
    if len(pos_list) > 1:
        print(f"MMSI: {mmsi}")
        for p in pos_list:
            print(f"  {p}")
