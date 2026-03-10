# 启动文档

本文档用于本地启动 `daily_stock_analysis` 项目，并覆盖最常用的运行方式。

## 1. 环境要求

- Python `3.10+`
- 推荐 Python `3.11`
- Node.js / npm
  - `--serve` / `--serve-only` 会自动构建前端

## 2. 首次安装

在项目根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. 最小配置

至少修改 `.env` 里的这些项：

```env
STOCK_LIST=600519,000001,AAPL

OPENAI_API_KEY=你的Key
OPENAI_BASE_URL=https://ai.novacode.top/v1
OPENAI_MODEL=gpt-5.4
OPENAI_VISION_MODEL=gpt-5.4
OPENAI_API_STYLE=responses

TAVILY_API_KEYS=你的TavilyKey
AGENT_MODE=true
```

说明：

- `STOCK_LIST`：默认监控股票列表
- `OPENAI_*`：当前最常用的 OpenAI 兼容配置
- `OPENAI_API_STYLE=responses`：适用于只支持 `/v1/responses` 的网关
- `TAVILY_API_KEYS`：可选，但建议配置；用于新闻搜索增强
- `AGENT_MODE=true`：如果要使用网页里的策略问股 / AI 对话，建议开启

注意：

- `.env` 中显式配置的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`OPENAI_API_STYLE`、`TAVILY_API_KEYS` 等值会优先于外部 shell 中同名环境变量

## 4. 启动方式

### 4.1 启动 Web 页面和 API

最常用方式：

```bash
source .venv/bin/activate
python main.py --serve-only --host 127.0.0.1 --port 8000
```

启动后访问：

- 首页：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

说明：

- `--serve-only`：只启动 Web / API 服务，不自动跑分析
- `--serve`：启动服务后顺便执行一轮分析

### 4.2 命令行执行单次分析

```bash
source .venv/bin/activate
python main.py --stocks 600519 --no-notify
```

常用参数：

- `--stocks 600519,000001,AAPL`：覆盖 `.env` 中的股票列表
- `--no-notify`：不发推送
- `--market-review`：只跑大盘复盘
- `--force-run`：跳过交易日检查

### 4.3 运行回测

回测是对历史分析记录做效果验证，不是重新跑 AI 分析。

```bash
source .venv/bin/activate
python main.py --backtest
```

只回测单只股票：

```bash
python main.py --backtest --backtest-code 600519 --backtest-force
```

常用参数：

- `--backtest-code 600519`：只回测指定股票
- `--backtest-days 10`：评估窗口交易日数
- `--backtest-force`：即使已有结果也重新算

## 5. 停止项目

如果当前是前台启动：

```bash
Ctrl+C
```

如果你之前把服务挂到后台了，可以先找进程：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

然后停止：

```bash
kill <PID>
```

## 6. 常见告警说明

下面这些通常不是启动失败：

- `未配置 Tushare Token，将使用其他数据源`
  - 正常，可忽略

- `未配置 Gemini/Anthropic API Key，将使用 OpenAI 兼容 API`
  - 如果你已经配置了 `OPENAI_API_KEY`，这条是正常的

- `未配置通知渠道，将不发送推送通知`
  - 只影响企业微信 / 飞书 / Telegram / 邮件推送，不影响网页使用

## 7. 常用排查

### 7.1 端口占用

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <PID>
```

### 7.2 网页能打开，但 AI 分析失败

优先检查：

- `.env` 中的 `OPENAI_API_KEY`
- `.env` 中的 `OPENAI_BASE_URL`
- `.env` 中的 `OPENAI_MODEL`
- `.env` 中的 `OPENAI_API_STYLE`
- `AGENT_MODE` 是否开启

### 7.3 相关资讯为空

检查：

- `TAVILY_API_KEYS`
- `BOCHA_API_KEYS`
- `BRAVE_API_KEYS`
- `SERPAPI_API_KEYS`

如果都没配，系统会回退到 `GDELT` 公开新闻源。

## 8. 推荐启动顺序

如果你只是本地使用网页：

1. 激活虚拟环境
2. 检查 `.env`
3. 执行 `python main.py --serve-only --host 127.0.0.1 --port 8000`
4. 打开 `http://127.0.0.1:8000`
5. 在页面里直接分析股票或运行回测
