# ADR-065: Lyria Audio — Opt-in Generation
Status: Accepted.

Context: Audio generation (~$0.02-0.05/clip) is cheap but not every mission needs
audio. Auto-triggering Lyria would bloat workspace folders and confuse judges
who just asked for a travel recommendation.

Decision: Lyria is strictly opt-in. It triggers only when the goal explicitly
mentions audio/briefing/podcast/voiceover/narration/listen. The island demo
remains images-only unless the user adds "and make me an audio guide" or similar.

Consequences: Cost stays predictable. Workspace folders stay clean. Users who
want a narrated podcast version of their research get exactly that; users who
just want a doc aren't surprised by a WAV file.