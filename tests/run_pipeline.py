#!/usr/bin/env python3
"""End-to-end test: render, video, page reading, check (and every way it should fail), schedule,
preview, log and results, on a copy of the example in a work folder.

    python3 tests/run_pipeline.py work
"""
import http.server, json, os, shutil, socketserver, subprocess, sys, threading
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "pinterest-skill")
SCRIPTS = os.path.join(SKILL, "scripts")
PY = sys.executable
FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
for _s in (sys.stdout, sys.stderr):   # the test prints script output, emoji included, on any console
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run(*args, ok=True, cwd=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    args = list(args)
    if cwd and cwd != WORK:   # paths given relative to WORK
        args = [args[0]] + [os.path.join(WORK, x) if x.endswith((".json", ".csv")) else x for x in args[1:]]
    r = subprocess.run([PY, os.path.join(SCRIPTS, args[0])] + args[1:], capture_output=True, text=True,
                       cwd=cwd or WORK, encoding="utf-8", errors="replace", env=env)
    out = r.stdout + r.stderr
    print(f"$ {' '.join(args)}\n{out.strip()[:1500]}\n")
    if ok is True:
        assert r.returncode == 0, f"{args[0]} failed:\n{out}"
    elif ok is False:
        assert r.returncode != 0, f"{args[0]} should have failed:\n{out}"
    return out


def plan():
    with open(os.path.join(WORK, "plan.json"), encoding="utf-8") as f:
        return json.load(f)


def write_plan(p, name="plan.json"):
    with open(os.path.join(WORK, name), "w", encoding="utf-8") as f:
        json.dump(p, f, indent=1)


def expect(out, *needles):
    for n in needles:
        assert n in out, f"expected '{n}' in output"


def serve(folder):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=folder, **k)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/old":
                self.send_response(301)
                self.send_header("Location", "/post.html")
                self.end_headers()
                return
            super().do_GET()
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    global WORK
    WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "work")
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.copytree(os.path.join(SKILL, "examples", "moon-phases"), WORK,
                    ignore=shutil.ignore_patterns("preview", "pins", "video", "*.bak", "check.json", "pins-log.jsonl", "results.md"))
    from PIL import Image

    # 1. render: image pins and the video frames, then a video pin
    out = run("render_pins.py", "pins.json", "--out", "pins/")
    expect(out, "phases-grid.jpg", "in the feed", "contact-sheet.jpg")
    for pid in ("phases-grid", "same-side", "cycle", "when-to-see"):
        with Image.open(os.path.join(WORK, "pins", pid + ".jpg")) as im:
            assert im.size == (1000, 1500), im.size
            assert not im.getexif(), "pins must carry no metadata"
    man = json.load(open(os.path.join(WORK, "pins", "manifest.json"), encoding="utf-8"))
    assert all("/Users/" not in json.dumps(m) and "\\" not in json.dumps(m) for m in man["pins"])
    out = run("render_pins.py", "pins.json", "--out", "pins/", "--only", "cycle")
    man = json.load(open(os.path.join(WORK, "pins", "manifest.json"), encoding="utf-8"))
    assert len(man["pins"]) == 4, "--only must keep the other pins in the manifest"
    os.makedirs(os.path.join(WORK, "video"), exist_ok=True)
    shutil.copyfile(os.path.join(SKILL, "examples", "moon-phases", "video", "phases.mp4"), os.path.join(WORK, "video", "phases.mp4"))
    frames = [os.path.join("media", f"phase-{i}.jpg") for i in (5, 6, 7, 8, 1)]
    if FF:
        out = run("video.py", "stills", *frames, "--seconds", "1.1", "--fade", "0", "--out", "video/cuts.mp4")
        expect(out, "1000x1500", "hard cuts")
        out = run("video.py", "stills", *frames[:3], "--seconds", "1.5", "--out", "video/fades.mp4")
        expect(out, "1000x1500")
        run("video.py", "frames", "video/cuts.mp4", "--out", "video/")
        assert os.path.exists(os.path.join(WORK, "video", "frames-sheet.jpg"))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25:duration=6",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-shortest", "-c:v", "mpeg4", "-c:a", "aac",
                        os.path.join(WORK, "land.mov")], check=True)
        out = run("video.py", "fit", "land.mov", "--ratio", "2:3", "--x", "0.3", "--start", "1", "--out", "video/fit.mp4")
        expect(out, "1000x1500")
        out = run("video.py", "fit", "land.mov", "--ratio", "2:3", "--fit", "pad", "--bg", "black", "--speed", "2", "--out", "video/fast.mp4")
        expect(out, "(1000x1500, 3.", "drops the sound", "under Pinterest's 4 s minimum")
        out = run("video.py", "fit", "land.mov", "--ratio", "9:16", "--fit", "pad", "--out", "video/pad.mp4")
        expect(out, "1080x1920")

    # hostile render inputs: emoji the font can't draw, a transparent logo, a 16-bit PNG, a long word
    Image.new("RGBA", (400, 100), (0, 0, 0, 0)).save(os.path.join(WORK, "logo.png"))
    Image.new("I;16", (1200, 1800), 30000).save(os.path.join(WORK, "grey16.png"))
    hostile = {"brand": {"name": "x", "logo": "logo.png", "font": "Sans"},
               "pins": [{"id": "emoji", "layout": "photo", "image": "grey16.png", "headline": "Moon phases \U0001F319 tonight"},
                        {"id": "tiles", "layout": "grid", "headline": "Grid", "tiles": [{"image": "grey16.png", "label": "New \U0001F311"}, {"image": "grey16.png", "label": "Full"}]},
                        {"id": "longword", "layout": "fact", "big": "1", "headline": "Supercalifragilisticexpialidocious-moonphases"}]}
    json.dump(hostile, open(os.path.join(WORK, "hostile.json"), "w"))
    out = run("render_pins.py", "hostile.json", "--out", "hostile/")
    expect(out, "can't draw", "in a tile label")
    with Image.open(os.path.join(WORK, "hostile", "emoji.jpg")) as im:
        px = im.convert("L").getpixel((500, 1460))
        assert px > 30, f"transparent logo must not render as a black box ({px})"
        assert im.convert("L").getpixel((500, 900)) < 250, "16-bit greys must not render white"
    bad_id = {"pins": [{"id": "../escape", "layout": "fact", "big": "1", "headline": "x"}]}
    json.dump(bad_id, open(os.path.join(WORK, "badid.json"), "w"))
    out = run("render_pins.py", "badid.json", "--out", "hostile/", ok=False)
    expect(out, "becomes a file name")

    # 2. the example passes as it is
    out = run("pin_check.py", "plan.json")
    expect(out, "0 error(s)", "Nothing blocks")

    # 3. every failure the check must catch
    p = plan()
    Image.open(os.path.join(WORK, "media", "full-moon.jpg")).resize((900, 2100)).save(os.path.join(WORK, "tall.jpg"))
    Image.open(os.path.join(WORK, "pins", "cycle.jpg")).save(os.path.join(WORK, "cycle.webp"))
    Image.open(os.path.join(WORK, "media", "capitol-moon.jpg")).resize((1000, 1500)).convert("RGBA").save(os.path.join(WORK, "other.png"))
    Image.open(os.path.join(WORK, "pins", "when-to-see.jpg")).convert("CMYK").save(os.path.join(WORK, "cmyk.jpg"))
    if FF:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:size=1000x1500:rate=30:duration=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", os.path.join(WORK, "short.mp4")], check=True)
    bad = json.loads(json.dumps(p))
    pins = {x["id"]: x for x in bad["pins"]}
    pins["same-side"]["file"] = "pins/phases-grid.jpg"                         # same picture twice
    pins["cycle"]["file"] = "cycle.webp"                                        # wrong format (fixable)
    pins["cycle"]["title"] = "x" * 120                                          # too long
    pins["when-to-see"]["description"] += " #moon #astronomy, our #1 guide"     # hashtags (but not #1)
    pins["when-to-see"]["board"] = "Recipes"                                    # not a board
    if FF:
        pins["phases-video"]["file"] = "short.mp4"                              # under 4 s
    bad["pins"].append(dict(pins["when-to-see"], id="tall", file="tall.jpg", board="Moon and night sky",
                            title="Moon phases tall pin", link="https://bit.ly/abc"))   # too tall + shortener
    bad["pins"].append(dict(pins["when-to-see"], id="png", file="other.png", board="Moon and night sky",
                            title="Unrelated title about sourdough bread", description="Bake bread at home."))  # page mismatch
    bad["pins"].append(dict(pins["when-to-see"], id="typo", file="cmyk.jpg", board="Moon and night sky", link="mooon"))
    bad["pins"].append(dict(pins["when-to-see"], id="js", file="cmyk.jpg", board="Moon and night sky", link="javascript:alert(1)"))
    bad["pins"][0]["at"] = "2030-12-01T10:00"
    bad["pins"][2]["at"] = "2030-12-01T12:00Z"                                  # same page, other board, same day ('Z' accepted)
    write_plan(bad)
    out = run("pin_check.py", "plan.json", ok=False)
    expect(out, "looks the same as", "WEBP isn't accepted", "title is 120 characters", "hashtags (#moon #astronomy)",
           "isn't one of the account's boards", "taller than 1:2.1", "link shortener", "shares no words with its page",
           "to another board on the same day", "link 'mooon' is neither", "link 'javascript:alert(1)'",
           "CMYK colours")
    assert "#1" not in out.split("hashtags (")[1].split(")")[0]
    if FF:
        expect(out, "shorter than Pinterest's 4 s")
    out = run("pin_check.py", "plan.json", "--fix", ok=False)
    expect(out, "[fixed] cycle", "saved an RGB JPEG copy")
    assert plan()["pins"][3]["file"] == "fixed/cycle.jpg", plan()["pins"][3]["file"]

    # two pins for one page built from the same source photo
    src = json.loads(json.dumps(p))
    spec = json.load(open(os.path.join(WORK, "pins.json"), encoding="utf-8"))
    spec["pins"].append({"id": "copycat", "layout": "split", "image": "media/ksc-full-moon.jpg", "focus": [0.3, 0.6],
                         "headline": "The same Moon photo, new design"})
    json.dump(spec, open(os.path.join(WORK, "pins2.json"), "w"))
    run("render_pins.py", "pins2.json", "--out", "pins/")
    src["pins"].append(dict(src["pins"][2], id="copycat", file="pins/copycat.jpg", title="Moon phases copycat pin"))
    write_plan(src)
    out = run("pin_check.py", "plan.json", ok=False)
    expect(out, "uses the same photo as same-side (ksc-full-moon.jpg)")
    run("render_pins.py", "pins.json", "--out", "pins/")

    # explicit sources: a video and a pin made from the same clip for one page
    ex = json.loads(json.dumps(p))
    ex["pins"][1]["sources"] = ["clip-a"]
    ex["pins"][2]["sources"] = ["clip-a"]
    write_plan(ex)
    out = run("pin_check.py", "plan.json", ok=False)
    expect(out, "uses the same photo as phases-video (clip-a)")

    # burst: 6 pins on one day
    burst = plan()
    burst["pins"] = [dict(x, at="2030-12-02T09:00") for x in p["pins"]] + [dict(p["pins"][0], id="extra", at="2030-12-02T09:00")]
    write_plan(burst)
    out = run("pin_check.py", "plan.json", ok=False)
    expect(out, "6 pins on 2030-12-02", "reads as a burst")

    # 4. schedule: one a day, the same page 7 days apart, seasonal lead, stale requests removed
    for x in p["pins"]:
        x.pop("at", None)
    write_plan(p)
    open(os.path.join(WORK, "requests", "removed-pin.json"), "w").write("{}")
    out = run("schedule.py", "plan.json", "--start", "2030-03-02")
    assert not os.path.exists(os.path.join(WORK, "requests", "removed-pin.json")), "stale request must be removed"
    sp = plan()
    days = sorted(date.fromisoformat(x["at"][:10]) for x in sp["pins"])
    assert all((b - a).days >= 7 for a, b in zip(days, days[1:])), days
    expect(out, "Alt text to add in Pinterest")
    body = json.load(open(os.path.join(WORK, "requests", "phases-grid.json"), encoding="utf-8"))
    sa = body["socialAccounts"][0]
    assert sa["platform"] == "PINTEREST" and sa["link"].startswith("https://science.nasa.gov") and len(sa["title"]) <= 100
    assert body["schedule"]["type"] == "SCHEDULE_FOR_LATER" and body["schedule"]["scheduledFor"].endswith("Z")
    seasonal = json.loads(json.dumps(p))
    seasonal["links"]["moon-phases"]["moment"] = "2030-04-10"
    write_plan(seasonal)
    out = run("schedule.py", "plan.json", "--start", "2030-03-01")
    expect(out, "seasonal pins do best 45 to 90 days ahead")
    early = json.loads(json.dumps(p))
    early["links"]["moon-phases"]["moment"] = "2031-01-01"
    early["links"]["moon-phases"]["lead_days"] = [120, 60]
    write_plan(early)
    run("schedule.py", "plan.json", "--start", "2030-03-01")
    first = min(date.fromisoformat(x["at"][:10]) for x in plan()["pins"])
    assert first == date(2031, 1, 1) - timedelta(days=120), first
    late = json.loads(json.dumps(p))
    late["links"]["moon-phases"]["moment"] = "2030-03-20"
    late["links"]["moon-phases"]["lead_days"] = 30
    write_plan(late)
    out = run("schedule.py", "plan.json", "--start", "2030-03-01")
    expect(out, "isn't scheduled", "not scheduled (no request written)")
    lp2 = plan()
    assert all(date.fromisoformat(x["at"][:10]) < date(2030, 3, 20) for x in lp2["pins"] if x.get("at"))
    assert len(os.listdir(os.path.join(WORK, "requests"))) == sum(1 for x in lp2["pins"] if x.get("at"))
    z = json.loads(json.dumps(p))
    z["pins"][0]["at"] = "2030-06-01T12:00Z"
    write_plan(z)
    run("schedule.py", "plan.json", "--bodies-only")
    body = json.load(open(os.path.join(WORK, "requests", "phases-grid.json"), encoding="utf-8"))
    assert body["schedule"]["scheduledFor"] == "2030-06-01T12:00:00Z", body["schedule"]
    passed = json.loads(json.dumps(p))
    passed["links"]["moon-phases"]["moment"] = "2020-01-01"
    write_plan(passed)
    out = run("schedule.py", "plan.json", "--start", "2020-01-01")
    expect(out, "is in the past; scheduling from today", "has passed; scheduled as an evergreen pin")
    days = sorted(x["at"] for x in plan()["pins"])
    assert len(set(d[:10] for d in days)) == len(days), f"pins stacked on one day: {days}"
    typo = json.loads(json.dumps(p))
    typo["pins"][0]["link"] = "mooon"
    write_plan(typo)
    out = run("schedule.py", "plan.json", ok=False)
    expect(out, "neither a key in links")

    # 5. preview
    write_plan(p)
    run("schedule.py", "plan.json", "--start", "2030-03-02")
    nofile = plan()
    nofile["pins"].append({"id": "nofile", "account": "main", "link": "moon-phases", "board": "Moon and night sky"})
    write_plan(nofile, "plan-nofile.json")
    out = run("preview.py", "plan-nofile.json", "--out", "preview-nofile/")
    expect(out, "media file missing): nofile")
    out = run("preview.py", "plan.json", "--out", "preview/")
    html = open(os.path.join(WORK, "preview", "index.html"), encoding="utf-8").read()
    assert "Moon and night sky" in html and os.path.exists(os.path.join(WORK, "preview", "preview.png"))
    assert ("<video" in html) == bool(FF) or "<video" in html

    # 6. log (junk lines skipped), then a repeat is refused even with tracking parameters
    lp = plan()
    for i, x in enumerate(lp["pins"]):
        x["postId"] = f"post-{i}"
        x["at"] = (date.today() - timedelta(days=40 + 7 * i)).isoformat() + "T20:30"
    lp["pins"][0]["postId"] = "<from posts_create>"
    write_plan(lp)
    with open(os.path.join(WORK, "pins-log.jsonl"), "w", encoding="utf-8") as f:
        f.write('[1, 2]\n"text"\nnot json\n{"type": "pin", "postId": "x"}\n')
    out = run("log.py", "record", "plan.json")
    expect(out, "logged 4 new pin(s)")
    lp["pins"][0]["postId"] = "post-0"
    write_plan(lp)
    out = run("log.py", "record", "plan.json")
    expect(out, "logged 1 new pin(s)")
    again = plan()
    again["links"]["utm"] = dict(again["links"]["moon-phases"], url="https://science.nasa.gov/moon/moon-phases/?utm_source=pinterest&utm_medium=social")
    again["pins"] = [dict(again["pins"][0], id="repeat", postId=None, at=None, link="utm")]
    write_plan(again, "plan2.json")
    out = run("pin_check.py", "plan2.json", ok=False)
    expect(out, "already pinned to this page")
    src_again = plan()
    src_again["pins"] = [dict(src_again["pins"][2], id="new-design", postId=None, at=None, file="pins/copycat.jpg", sources=["media/ksc-full-moon.jpg"])]
    write_plan(src_again, "plan3.json")
    out = run("pin_check.py", "plan3.json", ok=False)
    expect(out, "uses a photo already pinned to this page")
    assert "redirects to" not in out, "a UTM tag is not a redirect"

    # 7. results: from day 30 and 1,000 impressions; views are not impressions
    metrics = {"socialAccountPosts": [
        {"postId": f"post-{i}", "socialAccountId": "x", "analytics": {
            "impressions": [{"date": date.today().isoformat(), "collectedAt": "", "value": 1000 * (i + 1)}],
            "views": [{"date": date.today().isoformat(), "collectedAt": "", "value": 40}],
            "saves": [{"date": date.today().isoformat(), "collectedAt": "", "value": 10 + i}],
            "clicks": [{"date": date.today().isoformat(), "collectedAt": "", "value": 5 * (5 - i)}]}} for i in range(5)]}
    json.dump(metrics, open(os.path.join(WORK, "metrics.json"), "w"))
    out = run("log.py", "results", "--plan", "plan.json", "--metrics", "metrics.json", cwd=os.path.dirname(WORK))
    expect(out, "Best design for this link so far: **phases-grid**", "per 1,000", "| 1,000 |")
    open(os.path.join(WORK, "analytics.csv"), "w").write("pin,measured,impressions,outbound_clicks\nsame-side,%s,1.2K,n/a\n" % date.today().isoformat())
    out = run("log.py", "results", "--plan", "plan.json", "--csv", "analytics.csv")
    expect(out, "1,200")

    # 8. page.py: redirects, headings, apostrophes, no local files
    site = os.path.join(WORK, "site")
    os.makedirs(site, exist_ok=True)
    open(os.path.join(site, "post.html"), "w").write(
        "<html><head><title>Moon phases guide</title><meta property=\"og:description\" content=\"Baker's guide to all 8 Moon phases.\">"
        "<meta property='og:image' content='file:///etc/hosts'>"
        "</head><body><nav><h2>Menu item</h2></nav><main><h1>Moon phases, explained</h1><p>" + "The Moon goes through eight phases. " * 4
        + "</p><img src='file:///etc/passwd'></main></body></html>")
    srv = serve(site)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    out = run("page.py", url + "/old", "--out", "page-test.json", "--images", "pageimgs")
    expect(out, "redirects to", "post.html")
    pg = json.load(open(os.path.join(WORK, "page-test.json"), encoding="utf-8"))
    assert "Moon phases, explained" in pg["headings"] and "Menu item" not in pg["headings"] and pg["final_url"].endswith("/post.html")
    assert pg["description"].startswith("Baker's guide"), pg["description"]
    assert not any(i["src"].startswith("file:") for i in pg["images"])
    assert not os.listdir(os.path.join(WORK, "pageimgs")), "no local files may be saved"
    out = run("page.py", url + "/missing.html", "--out", "page-404.json")
    assert json.load(open(os.path.join(WORK, "page-404.json")))["status"] == 404
    srv.shutdown()

    print("ALL PIPELINE CHECKS PASSED")


if __name__ == "__main__":
    main()
