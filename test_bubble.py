import json, time, pathlib
p = pathlib.Path.home() / ".claude/buddy/state.json"
s = json.loads(p.read_text()) if p.exists() else {}
s["speech"] = "good vibes only"
s["speech_ts"] = time.time()
p.write_text(json.dumps(s, indent=2))
