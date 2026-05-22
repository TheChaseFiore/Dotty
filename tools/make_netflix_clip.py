#!/usr/bin/env python3
"""Download a green-screen video and bake it into a 28x28 1-bit clip Dotty can play.

This is one-time preprocessing. Run it on a machine with internet access and
ffmpeg installed (the Pi is fine):

    pip install -r tools/requirements.txt
    python3 tools/make_netflix_clip.py                 # uses the default URL
    python3 tools/make_netflix_clip.py <URL> -o assets/netflix.npz

It chroma-keys the green background out (subject = anything not green), scales
to 28x28, and writes a compressed .npz of packed 1-bit frames (white logo on a
black field). main.py plays that file back with numpy only -- no OpenCV needed
at runtime.
"""
import argparse
import os
import sys
import tempfile

import numpy as np

DEFAULT_URL = "https://youtu.be/tH5z8x_diW8"
SIZE = 28


def download(url, dst_dir):
    import yt_dlp
    out = os.path.join(dst_dir, "src.%(ext)s")
    opts = {
        "format": "bestvideo[ext=mp4]/best[ext=mp4]/best",
        "outtmpl": out,
        "quiet": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)


def center_square(frame):
    h, w = frame.shape[:2]
    s = min(h, w)
    y0 = (h - s) // 2
    x0 = (w - s) // 2
    return frame[y0:y0 + s, x0:x0 + s]


def frame_to_bits(frame, h_lo, h_hi, s_min, v_min, lum_min):
    """Square-crop, drop the green background, downscale, return a 28x28 0/1 array."""
    import cv2
    sq = center_square(frame)
    hsv = cv2.cvtColor(sq, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (h_lo, s_min, v_min), (h_hi, 255, 255))
    fg = cv2.bitwise_not(green)                 # subject = anything not green
    gray = cv2.cvtColor(sq, cv2.COLOR_BGR2GRAY)
    fg[gray < lum_min] = 0                       # drop dark fringes / shadows
    small = cv2.resize(fg, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    return (small >= 128).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", default=DEFAULT_URL)
    ap.add_argument("-o", "--out", default="assets/netflix.npz")
    ap.add_argument("--fps", type=float, default=12.0, help="playback frames per second")
    ap.add_argument("--max-frames", type=int, default=300)
    ap.add_argument("--green", default="35,85",
                    help="green hue range lo,hi (OpenCV scale 0-179)")
    ap.add_argument("--s-min", type=int, default=70, help="min saturation counted as green")
    ap.add_argument("--v-min", type=int, default=40, help="min value counted as green")
    ap.add_argument("--lum-min", type=int, default=60,
                    help="subject pixels darker than this are dropped")
    args = ap.parse_args()

    try:
        import cv2  # noqa: F401
    except ImportError:
        sys.exit("OpenCV missing. Run: pip install -r tools/requirements.txt")

    h_lo, h_hi = (int(x) for x in args.green.split(","))

    with tempfile.TemporaryDirectory() as tmp:
        print(f"Downloading {args.url} ...")
        try:
            path = download(args.url, tmp)
        except Exception as e:
            sys.exit(f"Download failed: {e}\n(Is yt-dlp installed and ffmpeg on PATH?)")

        import cv2
        cap = cv2.VideoCapture(path)
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(src_fps / args.fps)))
        print(f"Source ~{src_fps:.1f} fps; sampling every {step} frame(s).")

        frames = []
        idx = 0
        while len(frames) < args.max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % step == 0:
                frames.append(frame_to_bits(frame, h_lo, h_hi,
                                            args.s_min, args.v_min, args.lum_min))
            idx += 1
        cap.release()

    if not frames:
        sys.exit("No frames decoded -- check the URL and that ffmpeg is installed.")

    arr = np.array(frames, dtype=np.uint8)        # (n, 28, 28) of 0/1
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    np.savez_compressed(args.out,
                        frames=np.packbits(arr),
                        shape=np.array(arr.shape, dtype=np.int64),
                        fps=np.float32(args.fps))
    lit = arr.mean() * 100
    print(f"Wrote {args.out}: {arr.shape[0]} frames @ {args.fps} fps, {lit:.1f}% lit avg")


if __name__ == "__main__":
    main()
