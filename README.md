# hermes-plugin-dashscope-video

Video generation plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) using Alibaba Cloud DashScope (Qwen Cloud).

Brings Alibaba's HappyHorse 1.1 video models to Hermes's `video_generate` tool. Works with token plan keys (`sk-sp-*`) and pay-as-you-go keys (`sk-ws-*`).

## Models

| Model | Mode | Strengths |
|-------|------|-----------|
| `happyhorse-1.1-t2v` | Text-to-video | Cinematic quality from text prompts |
| `happyhorse-1.1-i2v` | Image-to-video | Animate a still image |
| `happyhorse-1.1-r2v` | Reference-to-video | Style/character reference driven |

All models are included in the Alibaba Cloud AI Token Plan subscription and are available on the PAYG free tier. Generation takes ~2-3 minutes for a 5-second clip.

## Install

```bash
hermes plugins install rriggs/hermes-plugin-dashscope-video
hermes plugins enable dashscope
```

## Configure

All configuration lives under `video_gen.dashscope` in `config.yaml`:

```yaml
video_gen:
  provider: dashscope
  dashscope:
    api: https://token-plan.ap-southeast-1.maas.aliyuncs.com
    key_env: QWEN_API_KEY
    model: happyhorse-1.1-t2v    # optional
```

| Key | Default | Description |
|-----|---------|-------------|
| `api` | `https://token-plan.ap-southeast-1.maas.aliyuncs.com` | DashScope API base URL |
| `key_env` | `QWEN_API_KEY` | Name of the env var holding your API key |
| `model` | `happyhorse-1.1-t2v` | Default model for generation |

Set the API key in your `.env` file:

```bash
QWEN_API_KEY=***
```

### PAYG users

```yaml
video_gen:
  provider: dashscope
  dashscope:
    api: https://dashscope-intl.aliyuncs.com
    key_env: DASHSCOPE_API_KEY
```

No env var names are hard-coded -- `key_env` tells the plugin which env var to read.

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
1. POST {api}/api/v1/services/aigc/video-generation/video-synthesis
   (with X-DashScope-Async: enable header)
   --> returns task_id

2. GET {api}/api/v1/tasks/{task_id}
   --> poll until SUCCEEDED/FAILED

3. Download video from output.video_url
```

Both the token plan and PAYG endpoints require async mode for video models. The plugin handles the full submit-poll-download cycle with a 10-minute timeout.

## Requirements

- Hermes Agent v0.18+
- API key set in the env var named by `key_env`
- `requests` Python package (bundled with Hermes)

## License

MIT
