# -*- coding: utf-8 -*-
"""严谨复现 dsh 崩溃场景：72K 题面多轮 + 同前缀重发交替
原崩溃：Paged KV reservation invariant was violated（dsh 多轮使用中触发）
原报错：published MTP checkpoint is not materializable（同前缀第二轮）
在 8091 开发实例上跑（8081 在线实例零风险）。
"""
import sys, os, json, urllib.request, time
sys.path.insert(0, os.path.dirname(__file__))
from common import build_doc

API = "http://127.0.0.1:8091/v1/chat/completions"

def ask(messages, mx=300, timeout=1200):
    body = {"model": "qwen3.8-27b", "messages": messages, "max_tokens": mx, "temperature": 0}
    t0 = time.time()
    try:
        req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return {"ok": True, "content": r["choices"][0]["message"].get("content") or "",
                "usage": r.get("usage", {}), "elapsed": time.time() - t0}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:100]}", "elapsed": time.time() - t0}

def alive():
    try:
        a = ask([{"role": "user", "content": "ping"}], mx=5, timeout=20)
        return a.get("ok")
    except Exception:
        return False

if __name__ == "__main__":
    code = "DSH-42"
    doc, _, _ = build_doc(72000, [(0.3, f"CONFIDENTIAL: vault D code is {code}.")], seed=4242)
    q = doc + "\n\nWhat is the launch code for vault D? Code only."
    print(f"题面 72K（对齐事故现场 frontier≈71975）· 目标: 6 轮 dsh 式操作全存活且不崩\n")
    msgs = []
    for turn in range(1, 7):
        if turn == 1:
            msgs = [{"role": "user", "content": q}]                       # 冷预填+发布 host-backed
        elif turn in (2, 4):                                              # 同前缀逐字节重发（原 not materializable 炸点）
            msgs = [{"role": "user", "content": q}]
        elif turn == 3:
            msgs.append({"role": "user", "content": "And what year is referenced? Answer: unknown."})   # 会话续问
        elif turn == 5:
            msgs.append({"role": "user", "content": "Repeat the vault D code. Code only."})
        elif turn == 6:
            msgs.append({"role": "user", "content": "再换话题：一句话介绍黑洞。"})       # 分叉
        r = ask(msgs, mx=300 if turn != 6 else 200)
        ok = r.get("ok")
        hit = code.lower() in (r.get("content") or "").lower() if turn in (1, 2, 3, 5) else None
        print(f"turn{turn}: ok={ok} {r.get('elapsed', 0):.0f}s "
              f"{'命中=' + str(hit) if hit is not None else '闲聊轮'} "
              f"{'' if ok else 'ERR:' + str(r.get('error', ''))[:60]}")
        if not ok:
            print(f"\n❌ 第 {turn} 轮失败 —— 引擎可能已崩，验证存活...")
            print("存活:", alive())
            sys.exit(1)
        if turn in (1, 3, 5):
            msgs.append({"role": "assistant", "content": r["content"]})
    print(f"\n✅ 6 轮全部存活，无 invariant 崩溃、无 not materializable —— 降级修复在 dsh 场景成立")
