# Higgsfield integration

**Provider** = Higgsfield (server credentials `HIGGSFIELD_API_KEY_ID` + `HIGGSFIELD_API_KEY_SECRET`, or `HIGGSFIELD_API_KEY` as `id:secret`). Never frontend.

**Vendor** = underlying creator (`bytedance`, `kling`, `higgsfield`).

Auth header: `Authorization: Key KEY_ID:KEY_SECRET` (platform API). Async subscribe + poll.

## Documented Seedance 2.5 (CATALOG_ONLY)

| Internal id | Gateway id | Notes |
| --- | --- | --- |
| seedance-2.5-text-to-video | bytedance/seedance-2.5/text-to-video | prompt, duration 4–30, 480p/720p, aspect incl 9:16, generate_audio |
| seedance-2.5-image-to-video | bytedance/seedance-2.5/image-to-video | image_url required; optional end_image_url |
| seedance-2.5-reference-to-video | bytedance/seedance-2.5/reference-to-video | documented fields: duration, resolution, aspect_ratio, bitrate_mode, generate_audio — extra media keys not invented |
| seedance-2.5-video-edit | bytedance/seedance-2.5/video-edit | prompt + video_url |
| seedance-2.5-video-extend | bytedance/seedance-2.5/video-extend | prompt + video_url + duration |

No HTTP adapter yet.

## Kling (CATALOG_ONLY except legacy unimplemented slots)

- `kling-video/v3.0/4k/text-to-video`
- `kling-video/v3.0-turbo/text-to-video`
- `kling-video/v3.0/pro/image-to-video`
- `kling-video/v3/motion-control/pro` — requires `image_url` + `video_url`

## Genjutsu

Documented: `higgsfield/genjutsu/motion-transfer/v1.0` (`prompt`, `video_url`, `image_urls`, `resolution`). Product POST still disabled.

## Motion Designer

**Not** cinematic I2V. After Effects plugin + optional MCP `bridge.higgsfield.ai/mcp`. Marked `OPTIONAL_PRODUCTION_BACKEND`. MVP uses FFmpeg.
