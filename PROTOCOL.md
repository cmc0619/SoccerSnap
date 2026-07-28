# SoccerSnap Offload Protocol

Adapted from Traloxolcus-Claude `PROTOCOL.md`, with Chat-style confirm payloads.

## Flow

```
Pi / Rig                              Process station
───────                               ───────────────
1. Write media + nested manifest
2. POST /api/v1/upload  (file + sha256 + manifest)
                                      3. Store under sessions/{id}/{cam}/
                                      4. Verify SHA-256
   ◄── { checksum_verified: true }
5. POST /api/v1/upload/confirm
   ◄── { checksum_sha256 }
6. Compare digests; on match mark offloaded
7. Optional cleanup of offloaded local files
```

## Manifest

Nested PROTOCOL shape (`recording`, `file`, `video`, `timing`, `checksum`, `device`, `quality`) plus Chat flat fields (`offset_ms`, `offloaded`, `checksum.algo/value` via `.flat()`).

Session IDs: `GAME_YYYYMMDD_HHMMSS`  
Recording IDs: `{SESSION}_{CAM_L|CAM_C|CAM_R}`

## Confirm (Chat lean model)

```json
{
  "session_id": "GAME_20260728_150000",
  "camera_id": "CAM_C",
  "file": "GAME_20260728_150000_CAM_C.mp4",
  "checksum": { "algo": "sha256", "value": "…" }
}
```

Mismatch ⇒ refuse confirm (no delete).

## Scheduled start

CAM_C coordinator broadcasts `scheduled_start` (ISO-8601). Peers wait until that master instant, then record. Default delay: 2 seconds.

## Retry backoff

Attempts at 0s, 5s, 10s, 20s, 40s (max 5).
