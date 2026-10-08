# 3D pipeline

Every racket on Paladex is shown as a 3D model. There are three kinds, and the site always tells visitors which one they are looking at (the provenance badge on every viewer):

| Status | What it is | Where it comes from |
|---|---|---|
| `official` / `licensed` | The manufacturer's model, or one licensed from a third party | Supplied files, compressed with `npm run models:optimize` |
| `platform` | Built by Paladex from real photos of the racket: traced outline, printed face, measured details | `npm run models:trace` + a design file + `npm run models:build` |
| `placeholder` | A generic racket of the right shape class in our own colours. **Not** this racket's design | `npm run models:build` (parametric geometry) |
| `unavailable` | No model; the page shows a photo and "3D coming soon" | — |

## Conventions (every model must follow them)

- **Units:** metres. A racket is about 0.455 m long and 0.26 m wide.
- **Orientation:** +Y runs from the butt cap to the tip, +Z is the front face, X is across the face. The butt cap sits at y = 0.
- **Format:** binary glTF (`.glb`), Meshopt-compressed and quantized, with WebP textures. The viewer decodes Meshopt, Draco and Basis (decoders in `public/decoders/`, copied by `npm install`).
- **Two files per racket:** `<slug>.glb` (full) and `<slug>.preview.glb` (light version for cards, carousels and first paint). The viewer usually loads the preview first and swaps in the full model on racket pages.
- **Part names** (node names) let the viewer pull the layers apart ("material layers" view) and place notes. Only models that have `part_face_front` and have "Has separate parts for the layers view" switched on in the admin get the layers view.

| Part | What it is |
|---|---|
| `part_frame` | The frame (rim), including its printed top surface |
| `part_face_front`, `part_face_back` | The two hitting faces (carbon/fibreglass skins) |
| `part_face` | Preview models: one solid slab instead of the two faces and core |
| `part_core` | The foam core between the faces |
| `part_print`, `part_print_front`, `part_print_back` | Printed decals on the face |
| `part_bumper` | The protector at the top of the frame |
| `part_bridge` | The throat bridge, when the racket has one |
| `part_screws` | Adjustable weight screws (e.g. Metalbone, Metalbone HRD+) |
| `part_handle`, `part_grip`, `part_collar`, `part_cap` | Handle core, overgrip, the collar where the handle meets the frame, and the butt cap |

The explode offsets for each part are in `src/components/three/scene/RacketObject.tsx`.

## Platform models: from photos to a model

### One racket

1. **Photos.** Put them in `assets/reference/<slug>/`: a straight-on front view (transparent or plain background) plus angled and throat views. The slug looks like `brand-model-year`.
2. **Cut out the front photo** if it has a background:
   ```bash
   npx tsx scripts/cutout-racket-photo.ts --in <photo> --out assets/reference/<slug>/front.png
   ```
   - `--symmetric` drops wrist straps and cast shadows.
   - Lower `--tolerance` (e.g. 7) for white rackets.
   - `--close <px>` fills notches in pale frames on pale backgrounds.
3. **Trace the outline:**
   ```bash
   npm run models:trace -- --slug <slug> --image assets/reference/<slug>/front.png
   ```
   This writes `src/data/designs/<slug>.trace.json` (outline, throat, holes, scale) and a check image `.tmp/trace-<slug>.png`. If the green neck line is wrong, rerun with `--neck-y <px>` (the neck is about 137 mm from the butt).
4. **Design file.** Copy `src/data/designs/adidas-metalbone-3-4.ts` to `<slug>.ts` and adjust thickness, colours, the face's bottom edge, bevel, screws and `sweetSpotV`, judging from the angled photos. Register it in `src/data/designs/index.ts`.
5. **Build:**
   ```bash
   npm run models:build                        # every racket
   npm run models:build -- --only <slug>       # just one
   ```
   This writes `public/models/platform/<slug>.glb` and `.preview.glb`, and updates `src/data/models.generated.json` (sizes, triangle count, bounds, version).
6. **Photos and data.** Publish the display photos as WebP in `public/images/rackets/<slug>/` and add the racket to the seed files (see the README). Then run `npm run db:seed -- --force` and check `/rackets/<slug>`.

### A whole brand catalogue

This was used for the 34 rackets added on 6 Oct 2026:

1. Add the rackets to `src/data/seed/brand-catalogue.ts` (specs as the brand lists them, image URLs, product page). Reusing an existing slug updates that racket.
2. `npx tsx scripts/import-brand-catalogue.ts` downloads the photos to `assets/reference/<slug>/a.*, b.*, …`.
3. Pick the straight-on front view for each racket and cut it out (step 2 above), then trace it (step 3).
4. `npx tsx scripts/build-catalogue-designs.ts` writes `src/data/designs/catalogue.generated.ts`. Colours are sampled from the photo, the face's bottom edge sits 4 mm above the throat, and the sweet spot is set by shape. Per-racket overrides (e.g. the Metalbone HRD+ screws) are at the top of that script.
5. List the photos in `src/data/seed/catalogue-photos.generated.json` (the front photo is the cutout), then run `npm run models:build` and `npm run db:seed -- --force`.

### How a platform model is built

`scripts/generate-models.ts` builds each racket from its trace and design file with three.js geometry, then writes it with gltf-transform:

- The traced outline is extruded into the frame, with the chosen bevel. The faces sit inside it, with the photo projected onto the front.
- The holes come from the trace. Head photographs its holes as dark dots, so Head models have printed holes, not cut-through ones.
- The back face repeats the front print. Real back photos (e.g. Lok's "Front 2") would be an upgrade.
- Geometry is welded, deduplicated, pruned and Meshopt-compressed.

| Level of detail | Curve segments | Face texture | Grip texture |
|---|---|---|---|
| Full | 12 | 1024 px | 256 px |
| Preview | 5 | 512 px | 128 px |

Placeholder models use the parametric shapes in `src/lib/racket-geometry` (round, teardrop, hybrid, diamond) with the racket's colours from the admin's "Look" section. They go to `public/models/placeholders/`.

## Official and licensed models

When a brand or a licensor supplies a model:

1. Check the licence allows web display, and note the attribution and any restrictions.
2. Compress it and make the light version:
   ```bash
   npm run models:optimize -- --in path/to/model.glb --slug <slug>
   ```
   This writes `public/models/official/<slug>.glb` (WebP textures, at most 2048 px) and `<slug>.preview.glb` (about 35% of the triangles, 1024 px textures). Draco- or Meshopt-compressed inputs are decoded first.
   - `--out-dir` writes somewhere else. Upload the two files to your bucket in production.
   - `--ratio` changes how far the preview is simplified (default 0.35).
   - The script warns if the model isn't in metres or isn't oriented as above. Fix that in the source file; the script doesn't move or scale anything.
3. In the admin, open the racket's "3D model" section:
   - Paste the two URLs.
   - Set "Where the model comes from" to Official or Licensed, and fill in the licence, source, attribution and restrictions.
   - Switch on "Has separate parts" only if the model uses the part names above.
4. External URLs must be on a host listed in `ASSET_ORIGINS`, so the Content-Security-Policy lets the browser download them.

You can also upload a GLB directly in the admin (up to 25 MB). The upload is checked (extension, file signature, self-contained glTF), but it isn't compressed, so run `models:optimize` first.

## Hotspots, notes and overlays

- **Hotspots** are the points on the model that explain a spec (sweet spot, face, balance point…). Positions are fractions of the model's bounding box: u across (0 = left, 1 = right), v from butt (0) to tip (1), w from back (0) to front (1).
- **Notes** caption each camera view (front, side, back…).
- **Overlays** draw on the model (sweet spot, impact zone, balance point and more; see `OVERLAY_INFO` in `src/domain/vocab.ts`).
- Every hotspot, note and overlay carries a basis that the site shows: manufacturer data, platform evaluation (Paladex's own assessment) or illustration.
- `src/lib/model-defaults.ts` derives all three from the specs and the model's geometry. The seed uses it, and so does the admin's "Regenerate from specs".

## Known limits

- Head models have printed holes (see above).
- The Wilson Defy's print is soft: its only photo is 400 px.
- The Wilson Bela Pro V3 has only an angled photo, and the Babolat Technical Viper Soft 3.0 and Technical Veron 3.0 have no photos, so they keep placeholder models.
