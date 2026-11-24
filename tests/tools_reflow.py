"""Re-wraps markdown prose to a readable width (no long horizontal scrolling). Code blocks, headings, rules untouched."""
import re, sys, textwrap
WIDTH = 96

def reflow(text: str) -> str:
    out, para, in_code = [], [], False
    item = None   # (indent, bullet)
    def flush():
        nonlocal para, item
        if not para: return
        body = " ".join(s.strip() for s in para)
        if item:
            indent, bullet = item
            out.append(textwrap.fill(body, WIDTH, initial_indent=indent + bullet, subsequent_indent=indent + " " * len(bullet),
                                     break_long_words=False, break_on_hyphens=False))
        else:
            out.append(textwrap.fill(body, WIDTH, break_long_words=False, break_on_hyphens=False))
        para, item = [], None
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            flush(); in_code = not in_code; out.append(line); continue
        if in_code or line.startswith("#") or line.strip() in ("---", "***") or line.startswith("|") or line.startswith("<"):
            flush(); out.append(line); continue
        if not line.strip():
            flush(); out.append(""); continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if m:
            flush(); item = (m.group(1), m.group(2) + " "); para = [m.group(3)]; continue
        para.append(line)
    flush()
    return "\n".join(out)

if __name__ == "__main__":
    for path in sys.argv[1:]:
        t = open(path, encoding="utf-8").read()
        open(path, "w", encoding="utf-8").write(reflow(t).rstrip() + "\n")
        longest = max(len(l) for l in open(path, encoding="utf-8").read().split("\n"))
        print(path, "longest line:", longest)
