# -*- coding: utf-8 -*-
"""95K+ 规模长会话工具调用验证（用户实际翻车规模）
构造 ~95K 会话（长系统段落 + 工具 + 多轮工具交互历史），再跑 4 轮 edit 类工具
调用（用户翻车的正是 edit 调用），判定格式稳定性。"""
import sys, os, json, urllib.request, urllib.error, time
sys.path.insert(0, os.path.dirname(__file__))
from common import build_doc

API = "http://127.0.0.1:8081/v1/chat/completions"
TOOLS = [{"type": "function", "function": {"name": n, "description": d,
          "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in args},
                         "required": args}}}
         for n, d, args in [
             ("edit", "Edit a file: replace old_string with new_string", ["file_path", "old_string", "new_string"]),
             ("write_file", "Write a file", ["path", "content"]),
             ("run_command", "Run a shell command", ["command"]),
             ("read_file", "Read a file", ["path"]),
             ("list_dir", "List directory", ["path"])]]
LEGAL = {t["function"]["name"] for t in TOOLS}

def ask(msgs, mx=16384):
    body = {"model": "qwen3.8-27b", "messages": msgs, "max_tokens": mx,
            "temperature": 0.7, "tools": TOOLS}
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(
            API, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}), timeout=1800))
        ch = r["choices"][0]
        tc = ch["message"].get("tool_calls")
        return {"ok": True, "finish": ch.get("finish_reason"),
                "names": [t["function"]["name"] for t in tc] if tc else None,
                "args_head": (tc[0]["function"]["arguments"][:80] if tc else ""),
                "content": ch["message"].get("content") or "",
                "prompt_tok": r.get("usage", {}).get("prompt_tokens"),
                "elapsed": time.time() - t0}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: " + e.read().decode('utf-8','replace')[:200], "elapsed": time.time() - t0}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "elapsed": time.time() - t0}

if __name__ == "__main__":
    # ~93K 前缀：长文档 + 初始任务 + 3 轮成功的工具交互历史（含 edit 范例）
    doc, _, _ = build_doc(88000, [(0.5, "NOTE: reference tag is RX-55.")], seed=99)
    msgs = [
        {"role": "system", "content": "You are a front-end animation engineer. Use tools for all file operations."},
        {"role": "user", "content": doc + "\n\nTask: build C:/test/pelican.html, a pelican riding a bicycle with SVG+JS animation."},
        {"role": "assistant", "content": "I'll start by checking the directory, then write the file.",
         "tool_calls": [{"id": "h1", "type": "function", "function": {"name": "list_dir", "arguments": "{\"path\": \"C:/test\"}"}}]},
        {"role": "tool", "tool_call_id": "h1", "content": "(empty directory)"},
        {"role": "assistant", "content": "Writing the initial file.",
         "tool_calls": [{"id": "h2", "type": "function", "function": {"name": "write_file",
          "arguments": "{\"path\": \"C:/test/pelican.html\", \"content\": \"<svg>...skeleton...\"}"}}]},
        {"role": "tool", "tool_call_id": "h2", "content": "File written (mock)."},
        {"role": "assistant", "content": "Now refining the animation.",
         "tool_calls": [{"id": "h3", "type": "function", "function": {"name": "edit",
          "arguments": "{\"file_path\": \"C:/test/pelican.html\", \"old_string\": \"@keyframes old\", \"new_string\": \"@keyframes blink\"}"}}]},
        {"role": "tool", "tool_call_id": "h3", "content": "Edit applied (mock)."},
        {"role": "user", "content": "复查代码后修复这些 bug：1) 眨眼 keyTimes 顺序错误 2) 高光飘出闭眼 3) 围巾画在身体上面 4) 翅膀尖没搭在握把 5) 尾灯悬空 6) 鱼尾鳍戳穿车篮 7) 沥青暗斑不滚动。逐个用 edit 修复。"},
    ]
    fails = 0
    for i in range(4):
        r = ask(msgs)
        legal = bool(r.get("names")) and all(n in LEGAL for n in (r.get("names") or []))
        print(f"轮{i+1}: [{'OK' if r.get('ok') and legal else 'FAIL'}] prompt={r.get('prompt_tok')} "
              f"finish={r.get('finish')} tools={r.get('names')} {r.get('elapsed', 0):.0f}s")
        if r.get("ok") and not legal:
            print("   args头:", r.get("args_head"))
            print("   content尾:", repr((r.get("content") or "")[-150:]))
        if not r.get("ok"):
            print("   err:", r.get("error")); break
        if legal:
            for j, t in enumerate(r["names"]):
                msgs.append({"role": "assistant", "content": "",
                             "tool_calls": [{"id": f"e{i}_{j}", "type": "function",
                                             "function": {"name": t, "arguments": "{}"}}]})
                msgs.append({"role": "tool", "tool_call_id": f"e{i}_{j}", "content": "OK (mock)"})
        else:
            fails += 1
            msgs.append({"role": "assistant", "content": (r.get("content") or "")[:400]})
            msgs.append({"role": "user", "content": "工具调用格式错误。必须用标准 tool_calls 格式重新调用 edit。"})
    print(f"\n判定: {'✅ 95K+ 规模工具调用稳定' if fails == 0 else f'❌ {fails} 轮畸形'}")
