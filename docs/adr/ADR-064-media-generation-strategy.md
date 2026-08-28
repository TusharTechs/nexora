# ADR-064: Media Generation Strategy (Imagen for images, Veo gated)
Status: Accepted.

Context: Video generation (Veo) costs ~$0.30-0.50/second; image generation (Imagen)
costs ~$0.02-0.04/image. The demo needs rich visuals without burning GCP credits.

Decision: Images are generated with Vertex Imagen (imagen-3.0-generate-002) and
uploaded as PNGs into the mission Drive folder. Veo remains available but is only
triggered by explicit video vocabulary ("video", "trailer", "clip"). Travel and
recommendation goals automatically include imagen.generate_image for visuals.

Consequences: A full island-recommendation mission costs a few cents. Videos are
opt-in, so a judge cannot accidentally trigger an expensive render.