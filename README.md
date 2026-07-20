# hermes-plugin-dashscope-video

Video generation plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) using Alibaba Cloud DashScope (Qwen Cloud).

Brings Alibaba's HappyHorse 1.1 video models to Hermes's `video_generate` tool. Works with token plan keys (`sk-sp-*`) and pay-as-you-go keys (`sk-ws-*`).

## Models

| Model | Mode | Strengths |
|-------|------|-----------|
| `happyhorse-1.1-t2v` | Text-to-video | Cinematic quality from text prompts |
| `happyhorse-1.1-i2v` | Image-to-video | Animate a still image |
| `happyhorse-1.1-r2v` | Reference-to-video | Style/character reference driven |

All models are included in the Alibaba Cloud AI Token Plan subscription. Generation takes ~2-3 minutes for a 5-second clip.

## Install

```bash
hermes plugins install rriggs/hermes-plugin-dashscope-video
hermes plugins enable dashscope
```

## Configure

Set your API key in `~/.hermes/.env` (or your profile's `.env`):

```bash
QWEN_API_KEY=***
```

Then set the provider:

```bash
hermes config set video_gen.provider dashscope
```

For PAYG users (non-token-plan), also set the base URL:

```bash
# In .env:
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com
```

The default base URL points to the Singapore token plan endpoint.

## Usage

Once configured, Hermes's `video_generate` tool routes through DashScope automatically:

- **Text-to-video**: provide a prompt (routes to happyhorse-1.1-t2v)
- **Image-to-video**: provide `prompt` + `image_url` (auto-routes to happyhorse-1.1-i2v)
- **Reference-to-video**: provide `prompt` + `reference_image_urls` (routes to happyhorse-1.1-r2v)

Supported parameters: `duration` (3-10s), `aspect_ratio` (16:9, 9:16, 1:1, 4:3, 3:4).

Generated videos are cached locally under `$HERMES_HOME/cache/videos/` since DashScope OSS URLs expire.

## API Details

This plugin uses the native DashScope async task API:

```
1. POST {base}/api/v1/services/aigc/video-generation/video-synthesis
   (with X-DashScope-Async: enable header)
   --> returns task_id

2. GET {base}/api/v1/tasks/{task_id}
   --> poll until SUCCEEDED/FAILED

3. Download video from output.video_url
```

The token plan endpoint **requires** async mode for video models -- synchronous calls are rejected. The plugin handles the full submit-poll-download cycle with a 10-minute timeout.

## Requirements

- Hermes Agent v0.18+
- `QWEN_API_KEY` environment variable
- `requests` Python package (bundled with Hermes)

## License

MIT
