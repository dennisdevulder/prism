## PRISM triage — PR #11565: update osrs-tracker

⚠️ **REVIEW** — flagged signals below

- **Plugin**: `osrs-tracker` (UPDATE) by `dennisdevulder`, opened 2026-04-18
- **Source**: `dennisdevulder/osrs-tracker-plugin@c4851ded`
- **Manifest**: <https://raw.githubusercontent.com/dennisdevulder/osrs-tracker-plugin/c4851ded1b5edccb12ae92435f35618904e57f23/runelite-plugin.properties>
- **Description**: Automatically sends level-ups, quest completions, loot drops, clue scrolls, collection log updates, and deaths to osrs-tracker.com with video replay clips.

### Saturation — NOVEL-EXTENSION

cosine 0.64 vs universal-discord-notifications, adds novel: ['external-data-export', 'gpu-video-encoding', 'video-replay-capture', 'vulkan-integration']

Closest existing plugins:

- `universal-discord-notifications` (cosine **0.64**) — by **MidgetJake, Jake Barter**, first added 2022-08-08
  - Shared: `death-notification`, `level-notification`, `loot-notification`
  - This PR adds: `external-data-export`, `gpu-video-encoding`, `video-replay-capture`, `vulkan-integration`
- `dink` (cosine **0.48**) — by **pajlads, Mm2PL**, first added 2022-11-04
  - Shared: `death-notification`, `level-notification`, `loot-notification`
  - This PR adds: `external-data-export`, `gpu-video-encoding`, `video-replay-capture`, `vulkan-integration`
- `discord-notifications` (cosine **0.44**) — by **WintZ, William Winter**, first added 2021-10-20
  - Shared: `death-notification`, `level-notification`
  - This PR adds: `external-data-export`, `gpu-video-encoding`, `loot-notification`, `video-replay-capture`, `vulkan-integration`

### Risk — COMPLIANT

no rule matched

### T1 — code-level pointers (5 for reviewer attention)

_Examined 31 file(s) in update diff._

- ⚠️ **`src/main/java/com/osrstracker/OsrsTrackerConfig.java` L140-158** — Environment variable reading for API URL configuration (OSRS_TRACKER_API_URL) in dev mode
  - Dev mode can override the production URL endpoint via environment variables — verify this is intentional and not a vector for endpoint manipulation or credential interception
- 🛑 **`src/main/java/com/osrstracker/video/EventKind.java` L1-3** — Copyright header references VulkanEncoder.java but that file is not in the diff (31 files shown, 16 additional files not shown)
  - The PR claims Vulkan Video Encode support, but the critical video encoding implementation is truncated or not shown — verify the actual encoding implementation is present and matches the PR description
- ⚠️ **`src/main/java/com/osrstracker/OsrsTrackerPanel.java` L691-702** — Panel displays Vulkan encoder status via isVulkanEncoderActive() callback, but UI shows 'Vulkan't' as placeholder text
  - Verify that isVulkanEncoderActive() and Vulkan encoder implementation actually exist and are functional, not placeholder/stub code
- ℹ️ **`src/main/java/com/osrstracker/api/ApiClient.java` L1271-1276** — Authorization header constructed with apiToken concatenated directly into request: 'Bearer ' + apiToken
  - Verify API token is never logged, cached, or exposed in error messages; token is marked as secret in config but transmission should be reviewed
- ⚠️ **`src/main/java/com/osrstracker/bingo/BingoProgressReporter.java` L1680-1690** — HTTP request to /api/bingo/progress endpoint with Bearer token authentication; multiple video capture callbacks without explicit resource cleanup
  - Verify all HTTP callbacks properly close responses even on error; video capture callbacks in lines 1651, 1678, 1698, 1751, 1775, and elsewhere should ensure no resource leaks

### Reviewer notes

PRISM is a triage tool — every flag here is a suggestion, not a verdict. The reviewer makes the call.

_Packet: `runelite-plugin-hub@2026-04-28` · 1659 catalog entries · 34 rules_
