# API Guide

This document explains ChipCompiler's REST API.

## Server Startup

Start the backend server:

```bash
chipcompiler --host 127.0.0.1 --port 8765
```

Swagger UI:
- `http://127.0.0.1:8765/docs`

Health checks:
- `GET /health`
- `GET /api/workspace/health`
- `GET /sse/health`

## Request/Response Schema

Most workspace APIs use this envelope:

```json
{
  "cmd": "create_workspace",
  "data": {}
}
```

Response envelope:

```json
{
  "cmd": "create_workspace",
  "response": "success",
  "data": {},
  "message": []
}
```

## Workspace Endpoints

Base path: `/api/workspace`

- `POST /create_workspace`
- `POST /set_pdk_root`
- `POST /load_workspace`
- `POST /delete_workspace`
- `POST /rtl2gds`
- `POST /run_step`
- `POST /get_info`
- `POST /get_home_page`

## SSE Endpoints

Base path: `/sse`

- `GET /stream/{workspace_id}` for real-time flow notifications
- `GET /health`

## Related Documentation

- [Architecture](architecture.md)
- [Development Guide](development.md)
- [GUI Development Guide](gui-develop-guide.md)
