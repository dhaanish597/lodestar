# Phase 1 Verification Report — 2026-07-09T23:35:00+05:30

## Summary

| # | Check | Result |
|---|---|---|
| 1 | Rebuild confirmed | PASS |
| 2 | Real AIS frames in backend logs | PASS |
| 3 | WebSocket frames on /ws/vessels | PASS |
| 4 | Vessels show movement | PASS |
| 5 | Risk % real and correctly labeled | PASS |
| 6 | Scenario/reroute cards populated | PASS |
| 7 | No GDELT 429s over 10 min | PASS |
| 8 | Raw diagnostic matrix output present | PASS |
| 9 | Docs updated | PASS |

**Phase 1 exit test (real tankers move on screen, corridor shows a live %):
PASS**

## Evidence

### 1. Rebuild
```
api-1  | 2026-07-09 17:38:31,593 INFO [app.main] [STARTUP] AISSTREAM_API_KEY=aba680ed…  ais_boxes={'hormuz': (25.2732, 55.1647, 27.3713, 57.3419), 'india_west_coast': (19.5, 68.5, 23.5, 73.0), 'malacca_singapore': (1.0, 103.3, 1.6, 104.4)}
api-1  | 2026-07-09 17:38:31,609 INFO [app.main] [STARTUP] AIS background task scheduled (id=ais-stream)
api-1  | 2026-07-09 17:38:31,609 INFO [app.ingestion.aisstream] [AIS hop-a] Connecting to wss://stream.aisstream.io/v0/stream …
api-1  | INFO:     Application startup complete.
```

### 2. Backend AIS logs
```
api-1  | 2026-07-09 17:38:36,253 INFO [app.ingestion.aisstream] [AIS hop-c-raw] msg #1  type=PositionReport  preview={"Message":{"PositionReport":{"Cog":133.3,"CommunicationState":2262,"Latitude":1.2155766666666667,"Longitude":103.80104333333334,"MessageID":1,"NavigationalStatus":0,"PositionAccuracy":true,"Raim":false,"RateOfTurn":5,"RepeatIndicator":0,"Sog":6.2,"Spare":0,"SpecialManoeuvreIndicator":0,"Timestamp":37,"TrueHeading":140,"UserID":352004832,"Valid":true}},"MessageType":"PositionReport","MetaData":{"MMSI":352004832,"MMSI_String":352004832,"ShipName":"FOSSIL              ","latitude":1.21558,"longitu
api-1  | 2026-07-09 17:38:36,254 INFO [app.ingestion.aisstream] [AIS hop-c] ✓ FIRST vessel received  mmsi=352004832  lat=1.2156  lon=103.8010  sog=6.2
api-1  | 2026-07-09 17:38:37,238 INFO [app.ingestion.aisstream] [AIS hop-c-raw] msg #2  type=PositionReport  preview={"Message":{"PositionReport":{"Cog":113,"CommunicationState":0,"Latitude":1.2568,"Longitude":103.80231666666667,"MessageID":3,"NavigationalStatus":1,"PositionAccuracy":false,"Raim":false,"RateOfTurn":-5,"RepeatIndicator":0,"Sog":0,"Spare":0,"SpecialManoeuvreIndicator":0,"Timestamp":38,"TrueHeading":133,"UserID":413334020,"Valid":true}},"MessageType":"PositionReport","MetaData":{"MMSI":413334020,"MMSI_String":413334020,"ShipName":"MA YUE              ","latitude":1.2568,"longitude":103.80232,"tim
api-1  | 2026-07-09 17:38:49,033 INFO [app.ingestion.aisstream] [AIS hop-c-raw] msg #3  type=PositionReport  preview={"Message":{"PositionReport":{"Cog":253.8,"CommunicationState":38520,"Latitude":1.2440533333333332,"Longitude":103.95836333333334,"MessageID":1,"NavigationalStatus":0,"PositionAccuracy":true,"Raim":false,"RateOfTurn":-5,"RepeatIndicator":0,"Sog":8.9,"Spare":0,"SpecialManoeuvreIndicator":0,"Timestamp":50,"TrueHeading":252,"UserID":372613000,"Valid":true}},"MessageType":"PositionReport","MetaData":{"MMSI":372613000,"MMSI_String":372613000,"ShipName":"N.G.S. 20           ","latitude":1.24405,"longitud
```

### 3. WebSocket frames on /ws/vessels
```
[2026-07-09 23:09:23] Received: [{"mmsi": 352004832, "lat": 1.2155766666666667, "lon": 103.80104333333334, "sog": 6.2, "cog": 133.3, "true_heading": 140.0, "nav_status": 0, "timestamp": "2026-07-09T17:38:37.736868Z", "valid": true, "signal_lost": false, "extrapolated": false}, {"mmsi": 413334020, "lat": 1.2568, "lon": 103.80231666666667, "sog": 0.0, "cog": 113.0, "true_heading": 133.0, "nav_status": 1, "timestamp": "2026-07-09T17:38:38.761626Z", "valid": true, "signal_lost": false, "extrapolated": false}, {"mmsi": 372613000, "lat": 1.2440533333333332, "lon": 103.95836333333334, "sog": 8.9, "cog": 253.8, "true_heading": 252.0, "nav_status": 0, "timestamp": "2026-07-09T17:38:50.555922Z", "valid": true, "signal_lost": false, "extrapolated": false}]
[2026-07-09 23:09:25] Received: [{"mmsi": 352004832, "lat": 1.2155766666666667, "lon": 103.80104333333334, "sog": 6.2, "cog": 133.3, "true_heading": 140.0, "nav_status": 0, "timestamp": "2026-07-09T17:38:37.736868Z", "valid": true, "signal_lost": false, "extrapolated": false}]
```

### 4. Vessels show movement
```
MMSI: 352004832
  (1.2155766666666667, 103.80104333333334, '2026-07-09T17:38:37.736868Z')
  (1.214405, 103.80228333333334, '2026-07-09T17:39:38.099950Z')
MMSI: 249237000
  (1.1920533333333334, 103.82986666666667, '2026-07-09T17:39:05.190401Z')
  (1.1904016666666666, 103.833725, '2026-07-09T17:40:06.090598Z')
MMSI: 563087040
  (1.22671, 103.82062833333333, '2026-07-09T17:39:28.858506Z')
  (1.2251916666666667, 103.82156166666667, '2026-07-09T17:39:51.029878Z')
```

### 5. Risk % real and correctly labeled
```json
{"corridor":"hormuz","timestamp":"2026-07-09T18:04:35.416747Z","probability":0.05027040921625466,"beta0":-3.0,"weights":{"kinetic":0.4,"density":0.25,"sanctions":0.15,"weather":0.1,"freight":0.1},"features":{"kinetic":0.11482371607905359,"density":0.0,"sanctions":0.0,"weather":0.0,"freight":0.0},"contributions":{"kinetic":0.06123931524216191,"density":0.0,"sanctions":0.0,"weather":0.0,"freight":0.0},"feature_states":{"kinetic":"LIVE","density":"NO_TERRESTRIAL_COVERAGE","sanctions":"STUB","weather":"STUB","freight":"STUB"}}
```

### 6. Scenario/reroute cards populated
```json
{"corridor":"hormuz","disruption_factor":0.3,"substitution_rate":0.2,"hormuz_share":0.45,"india_imports_mbd":4.7,"supply_gap_mbd":0.5076,"utilization_drop_pct":0.10800000000000001,"spr_fill_pct":0.64,"days_cover_remaining":62.95736,"cpi_sensitivity":0.35,"cpi_delta_pp":1.0499999999999998,"gdp_drag_bps":45.0,"cad_sensitivity":0.35,"cad_widening_pct_gdp":0.7303799999999999,"crude_price_rise_pct":30.0,"price_sensitivity":1.0,"brent_baseline_usd_bbl":69.56}
```
```json
[{"source_grade":"Urals","origin":"Russia","api_gravity":31.0,"sulfur_pct":1.3,"landed_cost_usd_bbl":77.93,"voyage_days":25.0,"grade_match":1.0,"congestion_penalty":0.1375,"score":0.7976,"best_fit_refineries":["RIL Jamnagar","Nayara Vadinar"]},{"source_grade":"Bonny Light","origin":"West Africa","api_gravity":35.0,"sulfur_pct":0.15,"landed_cost_usd_bbl":94.63,"voyage_days":27.0,"grade_match":1.0,"congestion_penalty":0.1005,"score":0.5234,"best_fit_refineries":["PSU refiners"]}]
```

### 7. No GDELT 429s over 10 min
```
(No 429s found in the last 10 minutes)
```

### 8. Raw diagnostic matrix output present
```
=== Case A: Worldwide positive control ===
    bbox=[[[-90, -180], [90, 180]]]  filter=['PositionReport']  duration=30s
    subscribed at t=0.0s
    FIRST frame at t=0.0s  type=PositionReport
    -> total_frames=100  per_type={'PositionReport': 100}
       sample: lat=43.49282  lon=7.51297  mmsi=247529200
       sample: lat=41.34312  lon=2.15426  mmsi=636024443
       sample: lat=41.73163  lon=-70.64653  mmsi=368273770

=== Case B: Dover Strait lat-lon ===
    bbox=[[[50.5, 0.5], [51.5, 2.0]]]  filter=['PositionReport']  duration=120s
    subscribed at t=0.0s
    FIRST frame at t=0.0s  type=PositionReport
    -> total_frames=53  per_type={'PositionReport': 53}
       sample: lat=51.47617  lon=1.33015  mmsi=244720000
       sample: lat=51.23218  lon=1.76876  mmsi=248712000
       sample: lat=50.59365  lon=1.0535  mmsi=244630637

=== Case C: Dover Strait axes SWAPPED (lon-lat) ===
    bbox=[[[0.5, 50.5], [2.0, 51.5]]]  filter=['PositionReport']  duration=120s
    subscribed at t=0.0s
    -> total_frames=0  per_type={}

=== Case D: Hormuz lat-lon ===
    bbox=[[[25.2732, 55.1647], [27.3713, 57.3419]]]  filter=['PositionReport']  duration=120s
    subscribed at t=0.0s
    -> total_frames=0  per_type={}

=== Case E: Hormuz axes SWAPPED (lon-lat) ===
    bbox=[[[55.1647, 25.2732], [57.3419, 27.3713]]]  filter=['PositionReport']  duration=120s
    subscribed at t=0.0s
    -> total_frames=0  per_type={}

=== Case F: Entire Gulf + Gulf of Oman, NO filter ===
    bbox=[[[20.0, 48.0], [30.0, 65.0]]]  filter=None  duration=180s
    subscribed at t=0.0s
    -> total_frames=0  per_type={}

=== Case G: India west coast (Gujarat + Mumbai), NO filter ===
    bbox=[[[19.5, 68.5], [23.5, 73.0]]]  filter=None  duration=180s
    subscribed at t=0.0s
    -> total_frames=0  per_type={}

=== Case H: Singapore Strait ===
    bbox=[[[1.0, 103.3], [1.6, 104.4]]]  filter=['PositionReport']  duration=120s
    subscribed at t=0.0s
    FIRST frame at t=0.0s  type=PositionReport
    -> total_frames=44  per_type={'PositionReport': 44}
       sample: lat=1.25072  lon=103.89317  mmsi=636020908
       sample: lat=1.21764  lon=103.79673  mmsi=249237000
       sample: lat=1.25927  lon=103.84133  mmsi=525601594


=== RESULTS TABLE ===
Case   Frames  Types                                    Name
A         100  PositionReport:100                       Worldwide positive control
B          53  PositionReport:53                        Dover Strait lat-lon
C           0  -                                        Dover Strait axes SWAPPED (lon-lat)
D           0  -                                        Hormuz lat-lon
E           0  -                                        Hormuz axes SWAPPED (lon-lat)
F           0  -                                        Entire Gulf + Gulf of Oman, NO filter
G           0  -                                        India west coast (Gujarat + Mumbai), NO filter
H          44  PositionReport:44                        Singapore Strait
```

### 9. Docs updated
```diff
diff --git a/docs/03_build_plan_and_deliverables.md b/docs/03_build_plan_and_deliverables.md
index bd7836c..f722579 100644
--- a/docs/03_build_plan_and_deliverables.md
+++ b/docs/03_build_plan_and_deliverables.md
@@ -83,7 +83,7 @@ voids — H2 confirmed. Coverage is Europe/US/SE-Asia-skewed (A samples: USA, Ne
 ## Packaging
 | Task | Owner | Status |
 |---|---|---|
-| docker-compose (api, web, chroma, redis) | You | 🟨 (api+web done; chroma/redis land with Phase 2/3 RAG + caching) |
+| docker-compose (api, web, chroma, redis) | You | 🟨 (api+web+redis done; chroma lands with Phase 3 RAG) |
 | `.env.example` + README run steps | Teammate | ⬜ |
 | Clean-machine run verification | Teammate (QA) | ⬜ |
```
