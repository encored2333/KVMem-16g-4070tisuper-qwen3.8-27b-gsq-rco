# -*- coding: utf-8 -*-
"""KVMem 262,144 全程工具调用稳定性测试（用户验收标准）
三档规模（~95K / ~160K / ~240K 实际 token）× 每档 3 轮 edit 类调用。
行 token 密度实测 ~35/行（英文技术行），构造按此校准。"""
import sys, os, json, urllib.request, urllib.error, time

API = "http://127.0.0.1:8081/v1/chat/completions"
TOOLS = [{"type": "function", "function": {"name": n, "description": d,
          "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in args},
                         "required": args}}}
         for n, d, args in [
             ("edit", "Edit a file: replace old_string with new_string",
              ["file_path", "old_string", "new_string"]),
             ("write_file", "Write a file", ["path", "content"]),
             ("run_command", "Run a shell command", ["command"]),
             ("read_file", "Read a file", ["path"]),
             ("list_dir", "List directory", ["path"])]]
LEGAL = {t["function"]["name"] for t in TOOLS}
PER_LINE = 35  # 实测 token/行

def filler(n, seed=0):
    out = []
    for i in range(1, n + 1):
        out.append(f"Log entry {i:05d}: telemetry nominal, sector {(i * 7 + seed) % 97} stable, "
                   f"calibration drift {((i * 13) % 100) / 100:.2f} in tolerance, no action required.")
    return out

def build_session(target_tok):
    n = int(target_tok / PER_LINE)
    lines = filler(n - 300, seed=7)
    lines[int(len(lines) * 0.5)] = "NOTE: reference tag is RX-55."
    doc = "\n".join(lines)
    return [
        {"role": "system", "content": "You are a front-end animation engineer. Use tools for all file operations."},
        {"role": "user", "content": doc + "\n\nTask: refine C:/test/pelican.html (SVG+JS pelican bicycle animation)."},
        {"role": "assistant", "content": "Checking the current file first.",
         "tool_calls": [{"id": "h1", "type": "function",
                         "function": {"name": "read_file", "arguments": "{\"path\": \"C:/test/pelican.html\"}"}}]},
        {"role": "tool", "tool_call_id": "h1", "content": "(mock) <svg>...skeleton with headBob, blink keyTimes, scarf, wing, tail-light, basket, asphalt spots..."},
        {"role": "user", "content": "修复这些 bug：1) 眨眼 keyTimes 顺序错误 2) 高光飘出闭眼 3) 围巾画在身体上面 4) 翅膀尖没搭在握把 5) 尾灯悬空。逐个用 edit 修复。"},
    ]

def ask(msgs, mx=16384):
    body = {"model": "qwen3.8-27b", "messages": msgs, "max_tokens": mx,
            "temperature": 0.7, "tools": TOOLS}
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(
            API, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}), timeout=3600))
        ch = r["choices"][0]
        tc = ch["message"].get("tool_calls")
        return {"ok": True, "finish": ch.get("finish_reason"),
                "names": [t["function"]["name"] for t in tc] if tc else None,
                "args_head": (tc[0]["function"]["arguments"][:100] if tc else ""),
                "content": ch["message"].get("content") or "",
                "prompt_tok": r.get("usage", {}).get("prompt_tokens"),
                "elapsed": time.time() - t0}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: " + e.read().decode("utf-8", "replace")[:150],
                "elapsed": time.time() - t0}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "elapsed": time.time() - t0}

if __name__ == "__main__":
    for target in [95000, 160000, 240000]:
        msgs = build_session(target)
        fails = 0
        print(f"\n===== 档位 ~{target // 1000}K =====")
        for i in range(3):
            r = ask(msgs)
            legal = bool(r.get("names")) and all(n in LEGAL for n in (r.get("names") or []))
            print(f"  轮{i+1}: [{'OK' if r.get('ok') and legal else 'FAIL'}] prompt={r.get('prompt_tok')} "
                  f"finish={r.get('finish')} tools={r.get('names')} {r.get('elapsed', 0):.0f}s")
            if r.get("ok") and not legal:
                print("    args头:", r.get("args_head"))
                print("    content尾:", repr((r.get("content") or "")[-130:]))
                fails += 1
                msgs.append({"role": "assistant", "content": (r.get("content") or "")[:400]})
                msgs.append({"role": "user", "content": "工具调用格式错误，用标准 tool_calls 重新调用 edit。"})
            elif not r.get("ok"):
                print("    err:", r.get("error"))
                fails += 1
                break
            else:
                for j, t in enumerate(r["names"]):
                    msgs.append({"role": "assistant", "content": "",
                                 "tool_calls": [{"id": f"e{i}_{j}", "type": "function",
                                                 "function": {"name": t, "arguments": "{}"}}]})
                    msgs.append({"role": "tool", "tool_call_id": f"e{i}_{j}", "content": "OK (mock)"})
        print(f"  => {'✅' if fails == 0 else f'❌ {fails}'}")
