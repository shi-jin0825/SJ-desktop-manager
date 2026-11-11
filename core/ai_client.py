# -*- coding: utf-8 -*-
"""智谱 AI（GLM）大模型调用客户端。

独立封装：UI 主程序只 import 本模块的两个函数，绝不含任何网络请求代码。
API Key 通过环境变量 ZHIPU_API_KEY 注入，绝不出现在源码里。
"""
import json
import os
import urllib.error
import urllib.request

# ---- 配置 ----
# 智谱开放平台免费模型（Flash 系列）：速度快、额度免费，适合桌面助手。
# 也可换 glm-4-flashx / glm-4-plus 等，改这个常量即可。
API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-4-flash"

# 默认系统提示词：让墨墨以「桌面助手」人设回答
DEFAULT_SYSTEM_PROMPT = (
    "你是「墨墨」，一只住在用户电脑桌面上的小助手。"
    "回答简洁、口语化、友好，必要时可以带一点可爱的语气。"
    "用中文回答。"
)

# 网络/鉴权出错的兜底文案（用户要求：不能让程序崩溃，返回这句话）
NETWORK_ERROR_MSG = "墨墨现在有点头晕（网络错误）"


def _api_key() -> str:
    """从环境变量读取 API Key。未配置时抛 ValueError，由调用方兜底。"""
    key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "未配置 ZHIPU_API_KEY 环境变量。\n"
            "请在系统环境变量中设置后重启，或参考 README 的说明。"
        )
    return key


def _build_body(question: str, system_prompt: str) -> dict:
    """构造智谱 API 请求体（与 OpenAI 兼容的 chat/completions 格式）。"""
    return {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }


def _extract_answer(payload: dict) -> str:
    """从响应 JSON 里取出模型回复文本。"""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip()


def ask_ai(question: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    """同步调用智谱 GLM，返回模型回复文本。

    这是「子线程里执行」的同步函数——UI 侧应另起线程调用它，
    切不可在主线程直接调用（会阻塞界面 1-3 秒）。

    任何异常（断网 / Key 无效 / 余额不足 / 服务端错误）都会被捕获，
    统一返回兜底文案，绝不向上抛出导致程序崩溃。
    """
    try:
        key = _api_key()
    except ValueError as e:
        # Key 没配：返回友好提示（不崩）
        return f"墨墨还没拿到 API Key：{e}"

    body = _build_body(question, system_prompt)
    data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        answer = _extract_answer(payload)
        return answer if answer else "墨墨想了半天，没想出来～"
    except urllib.error.HTTPError as e:
        # 401 = Key 无效 / 429 = 限流或余额不足 / 5xx = 服务端故障
        detail = ""
        try:
            err = json.loads(e.read().decode("utf-8"))
            detail = err.get("error", {}).get("message", "")
        except Exception:
            detail = ""
        if e.code == 401:
            return "墨墨的 API Key 好像不对，帮我检查一下～"
        if e.code == 429:
            return "墨墨今天的免费额度用完了（或请求太快），休息一下再来吧～"
        if detail:
            return f"墨墨有点头晕（{e.code}）：{detail}"
        return f"{NETWORK_ERROR_MSG}（{e.code}）"
    except (urllib.error.URLError, TimeoutError, OSError):
        return NETWORK_ERROR_MSG
    except Exception:
        return NETWORK_ERROR_MSG
