# ascii-art-hd

A [Claude](https://claude.ai) skill (plus a standalone CLI) that turns **images, GIFs and 3D `.obj` meshes** into **high-resolution, per-character-colour ASCII art** — still or animated/rotating.

![sphere](examples/sphere.png)
![torus](examples/torus.png)

*(Both examples are generated procedurally by the project's own test scripts; no third-party artwork.)*

## Why
Recognisable ASCII art (a horse's mane, armour plates, fur) needs **~160–260 columns, colour per character and a real source**. Hand-assembled low-resolution 3D blobs don't read as animals. This tool measures the real ink density of your font, keeps edges with directional characters (`- | / \`), and keeps the dark background empty so it works on transparent overlays.

## Install
```bash
pip install pillow numpy
```

## Use as a CLI
```bash
# still image
python ascii-art-hd/scripts/ascii_hd.py image photo.png --cols 220 --edges 0.35 --formats png,html,txt

# animated GIF
python ascii-art-hd/scripts/ascii_hd.py frames anim.gif --cols 120 --formats html,json

# rotating 3D model (Z-up Blender export, 48 frames per turn)
python ascii-art-hd/scripts/ascii_hd.py obj model.obj --up z --frames 48 --pitch 20 --mesh-color "#d4a050" --formats html,json
```
Run `--help` on a sub-command for every option. Outputs: `txt`, `ansi`, `html` (animated), `png`, and `json` ([ASCII Mate](https://github.com/naytngard/ascii-mate) `.ascii.json`, palette ≤ 62 colours).

## Use as a Claude skill
Zip the `ascii-art-hd/` folder (or use the prebuilt `ascii-art-hd.skill`) and add it as a skill in Claude. Then ask e.g. *"make a high-res colour ASCII version of this picture"* or *"turn this .obj into a rotating ASCII animation"*. The skill tells Claude to preview the PNG before delivering and to be honest about limits.

## Limits
- Needs a real source image/mesh; it converts, it does not invent.
- OBJ rendering is pure NumPy (fine to ~10k triangles), single colour, no textures.
- Respect copyright: only convert artwork you own or that is CC0/permissively licensed.

## Türkçe özet
Görüntü, GIF veya 3B `.obj` modelini **yüksek çözünürlüklü, karakter başına renkli ASCII sanatına** çevirir (durağan, hareketli veya dönen). Tanınabilir sonuç için ~160–260 sütun, gerçek bir kaynak (resim/mesh) ve renk gerekir; elle kurulmuş 50×24'lük şekiller hayvan gibi görünmez. Kurulum: `pip install pillow numpy`. Kullanım için yukarıdaki komutlara bakın. Çıktılar: txt, ansi, html, png ve ASCII Mate `.ascii.json`. Telif: yalnızca kendi eserinizi veya CC0/serbest lisanslı kaynakları dönüştürün.

## License
MIT — see [LICENSE](LICENSE).
